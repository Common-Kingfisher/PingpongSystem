"""参赛名单确认与双打智能配对。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlite3 import Connection

from .. import schemas
from ..db import get_db
from ..services import entries as entry_service
from ..services import teams as teams_service

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["entries"])


def _http(exc: entry_service.EntryError | teams_service.TeamError) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.get("/entries", response_model=list[schemas.EntryOut])
def list_entries(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        return entry_service.list_entries(conn, tournament_id)
    except entry_service.EntryError as exc:
        raise _http(exc)


@router.post("/pair-doubles", response_model=schemas.PairingResult)
def pair_doubles(
    tournament_id: int,
    payload: schemas.PairingRequest,
    conn: Connection = Depends(get_db),
):
    try:
        entries, unpaired, seed = entry_service.random_pair_doubles(
            conn, tournament_id, payload.pairing_seed
        )
    except entry_service.EntryError as exc:
        raise _http(exc)
    return schemas.PairingResult(
        entries=entries, unpaired_players=unpaired, pairing_seed=seed
    )


@router.post("/confirm-roster", response_model=schemas.ConfirmRosterResult)
def confirm_roster(tournament_id: int, conn: Connection = Depends(get_db)):
    try:
        tournament, entries = entry_service.confirm_roster(conn, tournament_id)
    except (entry_service.EntryError, teams_service.TeamError) as exc:
        # 团体赛的名单校验在 services/teams.py（TeamError），两者都带 code 字段。
        raise _http(exc)
    return schemas.ConfirmRosterResult(tournament=tournament, entries=entries)


@router.post("/entries/{entry_id}/withdraw", response_model=schemas.EntryWithdrawalResult)
def withdraw_entry(
    tournament_id: int,
    entry_id: int,
    payload: schemas.EntryWithdrawRequest,
    conn: Connection = Depends(get_db),
):
    try:
        entry, affected, preserved = entry_service.withdraw_from_tournament(
            conn, tournament_id, entry_id, payload.operator_name, payload.reason
        )
    except entry_service.EntryError as exc:
        raise _http(exc)
    return schemas.EntryWithdrawalResult(
        entry=entry,
        affected_match_ids=affected,
        preserved_finished_matches=preserved,
    )
