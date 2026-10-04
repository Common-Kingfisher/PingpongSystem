"""比赛路由：按赛制生成比赛、查看比赛列表。

赛制分发只有在 ``FormatHandler.generate_matches()`` 一处：本 router 只负责
读取赛事、解析 Handler、生成与错误映射，不实现任何比赛算法，也不按端点名
覆盖赛事已保存的 ``format_code``。
"""

from typing import Literal

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


def _existing_tournament(conn: Connection, tournament_id: int) -> dict:
    """读取赛事；不存在时沿用既有 404 文案，绝不把 ``None`` 传给 Handler。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return tournament


def _generate_matches_for_format(
    conn: Connection, tournament_id: int, format_code: str
) -> schemas.GenerateMatchesResult:
    """调用指定赛制的 Handler，并把服务层错误映射成既有的 HTTP 语义。"""
    try:
        handler = format_service.resolve_format_handler(format_code)
        result = handler.generate_matches(conn, tournament_id)
    except format_service.FormatHandlerError as exc:
        # 含 UnsupportedFormatError（422）与 Handler 自身的 404 / 409。
        raise HTTPException(status_code=exc.code, detail=str(exc)) from exc
    except matches_service.TournamentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        matches_service.TournamentStageError,
        matches_service.NoGroupsError,
        matches_service.MatchesExistError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return schemas.GenerateMatchesResult(
        matches_generated=result.matches_generated,
        per_group=result.per_group,
        tournament=schemas.TournamentOut(**_existing_tournament(conn, tournament_id)),
    )


def _reject_legacy_cross_format(tournament: dict) -> None:
    """legacy 小组赛入口不得被其它赛制借用。

    ``GROUP_KNOCKOUT`` 与尚未设置赛制的历史赛事继续可用（本入口的历史语义就是
    小组赛生成，这里不改写赛事赛制）；``ROUND_ROBIN`` / ``SINGLE_ELIMINATION``
    必须走 ``/generate-matches``，不能借端点名生成小组赛。
    """
    format_code = tournament.get("format_code")
    if format_code in (format_service.ROUND_ROBIN, format_service.SINGLE_ELIMINATION):
        raise HTTPException(
            status_code=409,
            detail=f"当前赛事赛制为 {format_code}，不能使用小组赛生成接口",
        )


@router.post("/generate-matches", response_model=schemas.GenerateMatchesResult)
def generate_matches(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """按赛事当前保存的 ``format_code`` 生成该赛制的首阶段比赛。

    这是三赛制唯一的正式生成入口。未设置赛制的历史赛事被显式拒绝，不默认成
    ``GROUP_KNOCKOUT``；TEAM 赛事由 Handler 拒绝，不产生普通 Match。
    """
    tournament = _existing_tournament(conn, tournament_id)
    format_code = tournament.get("format_code")
    if not format_code:
        raise HTTPException(
            status_code=422,
            detail="赛事尚未设置赛制，不能生成比赛；请先在赛事设置中保存赛制",
        )
    return _generate_matches_for_format(conn, tournament_id, format_code)


@router.post("/generate-group-matches", response_model=schemas.GenerateMatchesResult)
def generate_group_matches(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """legacy 小组赛生成入口：保留给既有前端、测试与 D6D harness。"""
    _reject_legacy_cross_format(_existing_tournament(conn, tournament_id))
    return _generate_matches_for_format(
        conn, tournament_id, format_service.GROUP_KNOCKOUT
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
