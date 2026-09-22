"""赛事路由：创建、列表、详情。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..dependencies import (
    get_current_user,
    require_event_admin,
    require_tournament_read,
    require_tournament_write,
)
from ..services import order_book as order_book_service
from ..services import tournament_export as tournament_export_service
from ..services import tournaments as tournament_service

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


@router.post("", response_model=schemas.TournamentOut, status_code=201)
def create_tournament(
    payload: schemas.TournamentCreate,
    conn: Connection = Depends(get_db),
    context=Depends(require_event_admin),
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
        owner_user_id=int(context.user["id"]),
    )


@router.get("", response_model=list[schemas.TournamentOut])
def list_tournaments(
    context=Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    return repo.list_tournaments_for_user(conn, int(context.user["id"]))


@router.get("/{tournament_id}/order-book-snapshot", response_model=schemas.OrderBookSnapshot)
def get_order_book_snapshot(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        return order_book_service.get_snapshot(conn, tournament_id)
    except order_book_service.OrderBookError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))


@router.get("/{tournament_id}/export", response_model=schemas.TournamentExport)
def export_tournament(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    """导出赛事结构化数据（只读）：落库数据 + 运行期推导结果，含 schema_version。

    建议在删除赛事前先调用本接口留存备份；导出不修改任何业务数据。
    """
    try:
        return tournament_export_service.get_export(conn, tournament_id)
    except tournament_export_service.ExportError as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))


@router.get("/{tournament_id}", response_model=schemas.TournamentOut)
def get_tournament(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    return tournament


@router.delete("/{tournament_id}", status_code=204)
def delete_tournament(
    tournament_id: int,
    confirm_name: str | None = Query(default=None),
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    """删除赛事（级联删除分组/选手/球台/比赛，见 db.py 外键 ON DELETE CASCADE）。

    不可恢复：删除前建议先调用 `GET /api/tournaments/{id}/export` 留存结构化备份。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="赛事不存在")
    if tournament["operation_mode"] == "LIVE" and confirm_name != tournament["name"]:
        raise HTTPException(
            status_code=409,
            detail="正式赛事删除前必须输入完整赛事名称确认；建议先导出备份（GET /api/tournaments/{id}/export）",
        )
    repo.delete_tournament(conn, tournament_id)
    conn.commit()
