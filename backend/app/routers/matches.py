"""比赛路由：按赛制生成比赛、查看比赛列表。

赛制分发只有在 ``FormatHandler.generate_matches()`` 一处：本 router 只负责
调用生成编排、把服务层错误映射成 HTTP 语义，不实现任何比赛算法，也不按端点名
覆盖赛事已保存的 ``format_code``，更不在取写锁之前读取 ``format_code``
（那样会引入"读到旧赛制 → 等锁 → 用旧 Handler 生成"的竞态）。

## 两个生成入口的冻结语义（PR #68 review Finding #3）

### Canonical：``POST /api/tournaments/{tid}/generate-matches``

"根据赛事当前已持久化的 ``format_code``，生成该赛制首阶段比赛的正式
format-aware API。" 支持 ``GROUP_KNOCKOUT`` / ``ROUND_ROBIN`` / ``SINGLE_ELIMINATION``。

```text
format_code = null  -> 422   （不默认成 GROUP_KNOCKOUT）
未知 / 非法 code     -> 422
TEAM                -> 拒绝，不生成任何普通 Match
```

### Legacy compatibility：``POST /api/tournaments/{tid}/generate-group-matches``

"兼容旧版 ``GROUP_KNOCKOUT`` / 历史未登记 ``format_code`` 的小组赛链路。"

**不得**称为新的正式赛制入口；已标记 ``deprecated=True``，但不删除
（既有前端主链、D6D harness 与历史测试仍依赖它）。

```text
GROUP_KNOCKOUT      -> 兼容可用
format_code = null  -> 保留历史兼容语义（它一直服务未登记赛制的历史赛事）
ROUND_ROBIN         -> 409
SINGLE_ELIMINATION  -> 409
TEAM                -> 拒绝
```

两个入口最终进入**同一个事务安全生成边界**
（``formats.generate_matches_for_tournament`` / ``generate_group_matches_compat``
共用 ``_run_generation``），因此 canonical 与 legacy 并发时只会有一个成功。
"""

from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..dependencies import (
    require_public_tournament_read,
    require_tournament_write,
)
from ..services import formats as format_service
from ..services import matches as matches_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["matches"])

#: 生成入口共用的错误语义。
#:
#: 两个入口都只用既有的 ``detail`` 字符串形态，**不**为一个 Low finding
#: （review Finding #5：legacy 跨赛制希望有稳定 code）发明第二种全仓 error model：
#: `{detail: {code, message}}` 目前只属于 A 轨 auth / system / tournament_admins，
#: matches / formats 业务域一直是 ``detail: string``。这里改为把语义写进 OpenAPI
#: 描述，语义边界因此对调用方可见，而不引入第二套错误体系。
_GENERATION_RESPONSES = {
    404: {"description": "赛事不存在。"},
    409: {
        "description": (
            "业务冲突（`detail` 为可读字符串）：阶段不允许生成、尚未分组、"
            "比赛/签表已生成，或写锁正被另一个生成请求持有"
            "（并发生成已被串行化，只会有一个成功）。"
        )
    },
}

#: FastAPI 默认 422 校验错误的 schema。canonical 入口既要保留它（请求体校验），
#: 又要说明"未设置赛制"这一**业务** 422，因此显式带上同一份 content。
_VALIDATION_ERROR_CONTENT = {
    "content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/HTTPValidationError"}}
    }
}

_CANONICAL_RESPONSES = {
    **_GENERATION_RESPONSES,
    422: {
        "description": (
            "422 有两种来源：① 路径/请求体校验失败（FastAPI 默认形态）；"
            "② 业务拒绝 —— 赛事尚未设置 `format_code`（**不**默认成 `GROUP_KNOCKOUT`），"
            "或 `format_code` 不在已支持赛制内。两者都用既有的 `detail` 字符串形态。"
        ),
        **_VALIDATION_ERROR_CONTENT,
    },
}

#: legacy 入口只额外说明业务 409；422 保持 FastAPI 默认（它没有业务 422 语义）。
_LEGACY_RESPONSES = {
    **_GENERATION_RESPONSES,
    409: {
        "description": (
            "业务冲突（`detail` 为可读字符串）：阶段不允许生成、尚未分组、"
            "小组比赛已生成、写锁被占用，或赛事已声明 `ROUND_ROBIN` / "
            "`SINGLE_ELIMINATION` —— 这两种赛制必须使用 `/generate-matches`，"
            "不能借小组赛端点生成。"
        )
    },
}


def _generate_matches_result(
    conn: Connection,
    tournament_id: int,
    generate: Callable[[], format_service.MatchGenerationResult],
) -> schemas.GenerateMatchesResult:
    """调用生成编排，并把服务层错误映射成既有的 HTTP 语义。"""
    try:
        result = generate()
    except format_service.FormatHandlerError as exc:
        # 含 UnsupportedFormatError（422）、未设置赛制（422）、legacy 跨赛制（409）、
        # 事务繁忙（409）与 Handler 自身的 404 / 409。
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc
    except matches_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        matches_service.TournamentStageError,
        matches_service.NoGroupsError,
        matches_service.MatchesExistError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return schemas.GenerateMatchesResult(
        matches_generated=result.matches_generated,
        per_group=result.per_group,
        tournament=schemas.TournamentOut(**tournament),
    )


@router.post(
    "/generate-matches",
    response_model=schemas.GenerateMatchesResult,
    responses=_CANONICAL_RESPONSES,
)
def generate_matches(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """按赛事当前保存的 ``format_code`` 生成该赛制的首阶段比赛。

    这是三赛制唯一的正式生成入口。赛事与 ``format_code`` 都在取得写锁之后重新读取，
    因此不会用过期 Handler 生成。
    """
    return _generate_matches_result(
        conn,
        tournament_id,
        lambda: format_service.generate_matches_for_tournament(conn, tournament_id),
    )


@router.post(
    "/generate-group-matches",
    response_model=schemas.GenerateMatchesResult,
    responses=_LEGACY_RESPONSES,
    deprecated=True,
)
def generate_group_matches(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """legacy 小组赛生成入口（已弃用，仍保留）：兼容旧前端主链、测试与 D6D harness。

    与统一入口共用同一个事务安全生成边界；`ROUND_ROBIN` / `SINGLE_ELIMINATION`
    赛事必须改用 `/generate-matches`。
    """
    return _generate_matches_result(
        conn,
        tournament_id,
        lambda: format_service.generate_group_matches_compat(conn, tournament_id),
    )


@router.get("/matches", response_model=list[schemas.MatchOut])
def list_matches(
    tournament_id: int,
    stage: Literal["GROUP", "KNOCKOUT"] | None = Query(default=None),
    status: Literal["WAITING", "PLAYING", "FINISHED"] | None = Query(default=None),
    group_id: int | None = Query(default=None),
    conn: Connection = Depends(get_db),
    _access=Depends(require_public_tournament_read),
):
    if repo.get_tournament(conn, tournament_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    matches = repo.list_matches(conn, tournament_id, stage=stage, status=status, group_id=group_id)
    return [schemas.MatchOut(**repo.decorate_match(conn, m)) for m in matches]
