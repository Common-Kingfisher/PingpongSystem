"""团体赛名单工作表 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import team_roster

router = APIRouter(prefix="/api/tournaments/{tournament_id}/team-roster", tags=["team-roster"])


def _http(exc: Exception) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("", response_model=schemas.TeamRosterSheetOut)
def get_sheet(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        return team_roster.get_sheet(conn, tournament_id)
    except Exception as exc:
        if hasattr(exc, "code"):
            raise _http(exc)
        raise


@router.put("", response_model=schemas.TeamRosterSheetOut)
def save_sheet(
    tournament_id: int,
    payload: schemas.TeamRosterSaveRequest,
    conn: Connection = Depends(get_db),
):
    try:
        return team_roster.save_sheet(conn, tournament_id, payload.model_dump())
    except Exception as exc:
        if hasattr(exc, "code"):
            raise _http(exc)
        raise


@router.post("/unconfirm", response_model=schemas.TeamRosterSheetOut)
def unconfirm(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        return team_roster.unconfirm_roster(conn, tournament_id)
    except Exception as exc:
        if hasattr(exc, "code"):
            raise _http(exc)
        raise
