"""赛前检查面板接口。"""

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_read
from ..services import preflight as preflight_service

router = APIRouter(tags=["preflight"])


@router.get("/api/tournaments/{tournament_id}/preflight", response_model=schemas.PreflightResult)
def inspect_tournament(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        return schemas.PreflightResult(**preflight_service.inspect_tournament(conn, tournament_id))
    except preflight_service.PreflightError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
