"""团体队伍路由：队伍即 Entry（entry_type='TEAM'），读写复用 EntryOut。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_read, require_tournament_write
from ..services import teams as teams_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}/teams", tags=["teams"])


def _http(exc) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("", response_model=list[schemas.EntryOut])
def list_teams(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        return teams_service.list_team_entries(conn, tournament_id)
    except teams_service.TeamError as exc:
        raise _http(exc)


@router.post("", response_model=schemas.EntryOut, status_code=201)
def create_team(
    tournament_id: int,
    payload: schemas.TeamEntryCreate,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        return teams_service.create_team_entry(
            conn,
            tournament_id,
            payload.display_name,
            payload.member_ids,
            payload.rating_points,
        )
    except teams_service.TeamError as exc:
        raise _http(exc)


@router.get("/{entry_id}", response_model=schemas.EntryOut)
def get_team(
    tournament_id: int,
    entry_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    try:
        return teams_service.get_team_entry(conn, tournament_id, entry_id)
    except teams_service.TeamError as exc:
        raise _http(exc)


@router.patch("/{entry_id}", response_model=schemas.EntryOut)
def update_team(
    tournament_id: int,
    entry_id: int,
    payload: schemas.TeamEntryUpdate,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        return teams_service.update_team_entry(
            conn,
            tournament_id,
            entry_id,
            payload.display_name,
            payload.member_ids,
            payload.rating_points,
        )
    except teams_service.TeamError as exc:
        raise _http(exc)


@router.delete("/{entry_id}", status_code=204)
def delete_team(
    tournament_id: int,
    entry_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        teams_service.delete_team_entry(conn, tournament_id, entry_id)
    except teams_service.TeamError as exc:
        raise _http(exc)
