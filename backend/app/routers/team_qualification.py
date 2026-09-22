"""团体晋级路由（A6.3）：查询 + 人工确认。

- `GET  /api/tournaments/{id}/qualification`：查看每组的晋级候选、是否已完赛、
  是否存在跨晋级线并列、是否可以确认，以及已经确认过的晋级队伍。
- `POST /api/tournaments/{id}/qualification/confirm`：人工确认晋级名单（全量替换）。

**为什么路径不带 `team-` 前缀**：任务书指定了 `GET /api/tournaments/{id}/qualification`；
与个人赛的人工裁定接口（`/qualification-decision`，单数、按小组）**不冲突**：
那条是按小组的裁定，本接口是团体赛的整赛事晋级确认，两者路由与语义都不同。

路由只做参数解析、调 service、错误映射；判定与校验全部在
`services/team_qualification.py`（域层纯算法在 `domain/team_qualification.py`）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_read, require_tournament_write
from ..services import team_qualification as qualification_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["team-qualification"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("/qualification", response_model=schemas.TeamQualificationOut)
def get_qualification(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        return qualification_service.get_qualification(conn, tournament_id)
    except qualification_service.ServiceError as exc:
        raise _http(exc)


@router.post("/qualification/confirm", response_model=schemas.TeamQualificationOut)
def confirm_qualification(
    tournament_id: int,
    payload: schemas.TeamQualificationConfirmRequest,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        return qualification_service.confirm_qualification(
            conn, tournament_id, payload.qualified_team_ids
        )
    except qualification_service.ServiceError as exc:
        raise _http(exc)
