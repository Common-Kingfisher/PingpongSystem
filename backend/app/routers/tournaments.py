"""赛事路由：创建、列表、详情。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import tournaments as tournament_service

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


@router.post("", response_model=schemas.TournamentOut, status_code=201)
def create_tournament(
    payload: schemas.TournamentCreate, conn: Connection = Depends(get_db)
):
    return tournament_service.create_tournament_with_tables(
        conn,
        payload.name,
        payload.date,
        payload.table_count,
        payload.group_count,
        payload.qualify_per_group,
    )


@router.get("", response_model=list[schemas.TournamentOut])
def list_tournaments(conn: Connection = Depends(get_db)):
    return repo.list_tournaments(conn)


@router.get("/{tournament_id}", response_model=schemas.TournamentOut)
def get_tournament(tournament_id: int, conn: Connection = Depends(get_db)):
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return tournament
