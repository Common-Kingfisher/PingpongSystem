"""种子路由：设置/调整/取消种子选手。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_write
from ..services import players as players_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["seeds"])


@router.put("/seeds", response_model=list[schemas.PlayerOut])
def set_seeds(
    tournament_id: int,
    payload: schemas.SetSeedsRequest,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        players = players_service.set_seeds(conn, tournament_id, payload.player_ids)
    except players_service.PlayerError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return [schemas.PlayerOut(**p) for p in players]


@router.post("/seeds/auto", response_model=list[schemas.PlayerOut])
def auto_seeds(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """按赛事积分自动生成种子（单打）：积分高者 S1…SN，同分按选手 id。"""
    try:
        players = players_service.auto_seed_by_rating(conn, tournament_id)
    except players_service.PlayerError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return [schemas.PlayerOut(**p) for p in players]
