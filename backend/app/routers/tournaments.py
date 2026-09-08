"""赛事路由：创建、列表、详情。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..services import order_book as order_book_service
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
        payload.event_type.value,
        payload.bronze_mode.value,
        payload.placement_mode.value,
        payload.games_to_win,
        payload.points_to_win,
        payload.operation_mode.value,
    )


@router.get("", response_model=list[schemas.TournamentOut])
def list_tournaments(conn: Connection = Depends(get_db)):
    return repo.list_tournaments(conn)


@router.get("/{tournament_id}/order-book-snapshot", response_model=schemas.OrderBookSnapshot)
def get_order_book_snapshot(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        return order_book_service.get_snapshot(conn, tournament_id)
    except order_book_service.OrderBookError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))


@router.get("/{tournament_id}", response_model=schemas.TournamentOut)
def get_tournament(tournament_id: int, conn: Connection = Depends(get_db)):
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return tournament


@router.delete("/{tournament_id}", status_code=204)
def delete_tournament(
    tournament_id: int,
    confirm_name: str | None = Query(default=None),
    conn: Connection = Depends(get_db),
):
    """删除赛事（级联删除分组/选手/球台/比赛，见 db.py 外键 ON DELETE CASCADE）。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    if tournament["operation_mode"] == "LIVE" and confirm_name != tournament["name"]:
        raise HTTPException(status_code=409, detail="正式赛事删除前必须输入完整赛事名称确认")
    repo.delete_tournament(conn, tournament_id)
    conn.commit()
