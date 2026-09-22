"""选手路由：列表、添加、修改、删除、批量导入。"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlite3 import Connection

from .. import repository as repo, schemas
from ..db import get_db
from ..dependencies import require_tournament_read, require_tournament_write
from ..services import import_players as import_service
from ..services import players as players_service
from ..services import teams as teams_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/players", tags=["players"])


def _ensure_tournament(conn: Connection, tournament_id: int) -> None:
    if repo.get_tournament(conn, tournament_id) is None:
        raise HTTPException(status_code=404, detail="赛事不存在")


@router.post("/import", response_model=schemas.ImportPlayersResult)
def import_players(
    tournament_id: int,
    file: UploadFile = File(...),
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail="文件过大，当前 Demo 仅支持 5MB 以内的名单文件"
        )
    try:
        result = import_service.import_players_file(
            conn, tournament_id, content, file.filename or ""
        )
    except (import_service.ImportFileError, teams_service.TeamError) as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return result


@router.post("/import/preview", response_model=schemas.ImportPreviewResult)
def preview_import_players(
    tournament_id: int,
    file: UploadFile = File(...),
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大，当前 Demo 仅支持 5MB 以内的名单文件")
    try:
        result = import_service.import_players_file(
            conn, tournament_id, content, file.filename or "", commit=False
        )
    except (import_service.ImportFileError, teams_service.TeamError) as exc:
        raise HTTPException(status_code=exc.code, detail=str(exc))
    return {
        "total_rows": result["total_rows"],
        "valid_rows": result["imported"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "rows": result["rows"],
    }


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("", response_model=list[schemas.PlayerOut])
def list_players(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    _ensure_tournament(conn, tournament_id)
    return repo.list_players(conn, tournament_id)


@router.post("", response_model=schemas.PlayerOut, status_code=201)
def add_player(
    tournament_id: int,
    payload: schemas.PlayerCreate,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        with teams_service._roster_write_tx(conn):
            players_service.ensure_players_editable(conn, tournament_id)
            players_service.ensure_player_capacity(len(repo.list_players(conn, tournament_id)), additions=1)
            player = repo.add_player(conn, tournament_id, payload.name, payload.college, payload.rating_points)
    except (players_service.PlayerError, teams_service.TeamError) as exc:
        raise _http(exc)
    return player


@router.patch("/{player_id}", response_model=schemas.PlayerOut)
def update_player(
    tournament_id: int,
    player_id: int,
    payload: schemas.PlayerUpdate,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        with teams_service._roster_write_tx(conn):
            players_service.ensure_players_editable(conn, tournament_id)
            player = repo.update_player(
                conn, player_id, payload.name, payload.college, payload.rating_points
            )
    except (players_service.PlayerError, teams_service.TeamError) as exc:
        raise _http(exc)
    if player is None:
        raise HTTPException(status_code=404, detail="选手不存在")
    return player


@router.delete("/{player_id}", status_code=204)
def delete_player(
    tournament_id: int,
    player_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        players_service.delete_player(conn, tournament_id, player_id)
    except (players_service.PlayerError, teams_service.TeamError) as exc:
        raise _http(exc)
