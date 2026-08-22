"""选手路由：列表、添加、修改、删除。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services.players import PlayerDeleteError, delete_player as service_delete_player

router = APIRouter(prefix="/api/tournaments/{tournament_id}/players", tags=["players"])


def _ensure_tournament(conn: Connection, tournament_id: int) -> None:
    if repo.get_tournament(conn, tournament_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")


@router.get("", response_model=list[schemas.PlayerOut])
def list_players(tournament_id: int, conn: Connection = Depends(get_db)):
    _ensure_tournament(conn, tournament_id)
    return repo.list_players(conn, tournament_id)


@router.post("", response_model=schemas.PlayerOut, status_code=201)
def add_player(
    tournament_id: int,
    payload: schemas.PlayerCreate,
    conn: Connection = Depends(get_db),
):
    _ensure_tournament(conn, tournament_id)
    player = repo.add_player(conn, tournament_id, payload.name, payload.college)
    conn.commit()
    return player


@router.patch("/{player_id}", response_model=schemas.PlayerOut)
def update_player(
    tournament_id: int,
    player_id: int,
    payload: schemas.PlayerUpdate,
    conn: Connection = Depends(get_db),
):
    _ensure_tournament(conn, tournament_id)
    player = repo.update_player(conn, player_id, payload.name, payload.college)
    if player is None:
        raise HTTPException(status_code=404, detail="选手不存在")
    conn.commit()
    return player


@router.delete("/{player_id}", status_code=204)
def delete_player(tournament_id: int, player_id: int, conn: Connection = Depends(get_db)):
    _ensure_tournament(conn, tournament_id)
    try:
        service_delete_player(conn, player_id)
    except PlayerDeleteError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
