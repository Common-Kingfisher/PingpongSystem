"""种子路由：设置/调整/取消种子选手。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import players as players_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["seeds"])


@router.put("/seeds", response_model=list[schemas.PlayerOut])
def set_seeds(
    tournament_id: int,
    payload: schemas.SetSeedsRequest,
    conn: Connection = Depends(get_db),
):
    try:
        players = players_service.set_seeds(conn, tournament_id, payload.player_ids)
    except players_service.PlayerError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return [schemas.PlayerOut(**p) for p in players]
