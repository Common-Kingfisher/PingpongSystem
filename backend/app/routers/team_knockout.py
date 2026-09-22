"""团体淘汰签路由（A6.4）：生成 + 查询。

- `POST /api/tournaments/{id}/team-knockout/generate`：按已确认的晋级名单生成团体淘汰签
  （全成或全不成；重复生成 409；未确认晋级 409）。
- `GET  /api/tournaments/{id}/team-knockout`：查询淘汰签（未生成时 `generated=false`）。

比赛单位复用 TeamTie（`stage='KNOCKOUT'`）；路由不含任何配对/晋级逻辑，
实现全部在 `services/team_knockout.py` 与 `domain/team_knockout.py`。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_read, require_tournament_write
from ..services import team_knockout as knockout_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/team-knockout", tags=["team-knockout"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("", response_model=schemas.TeamKnockoutOut)
def get_team_knockout(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        return knockout_service.get_team_knockout(conn, tournament_id)
    except knockout_service.ServiceError as exc:
        raise _http(exc)


@router.post("/generate", response_model=schemas.TeamKnockoutOut)
def generate_team_knockout(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        return knockout_service.generate_team_knockout(conn, tournament_id)
    except knockout_service.ServiceError as exc:
        raise _http(exc)
