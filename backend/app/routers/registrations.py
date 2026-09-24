"""报名开关、公开报名、管理员确认及赛事组织方/场馆 API。"""

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repository as repo, schemas
from ..db import get_db
from ..dependencies import require_tournament_read, require_tournament_write
from ..models import RegistrationStatus
from ..services import registrations as registrations_service
from ..services.transaction import TransactionBusyError, write_transaction

router = APIRouter(prefix="/api/tournaments/{tournament_id}", tags=["registrations"])


def _registration_http(exc: registrations_service.RegistrationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.error_code, "message": str(exc)},
    )


def _missing(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


@router.put("/registration", response_model=schemas.TournamentOut)
def update_registration_setting(
    tournament_id: int,
    payload: schemas.TournamentRegistrationUpdate,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        return registrations_service.update_registration_setting(
            conn, tournament_id, enabled=payload.enabled
        )
    except registrations_service.RegistrationError as exc:
        raise _registration_http(exc) from None


@router.post(
    "/registrations",
    response_model=schemas.RegistrationPublicOut,
    status_code=201,
)
def submit_registration(
    tournament_id: int,
    payload: schemas.RegistrationCreate,
    conn: Connection = Depends(get_db),
):
    try:
        registration = registrations_service.create_pending_registration(
            conn,
            tournament_id,
            name=payload.name,
            affiliation=payload.affiliation,
            contact=payload.contact,
            rating_points=payload.rating_points,
        )
    except registrations_service.RegistrationError as exc:
        raise _registration_http(exc) from None
    return {
        "registration_id": registration["id"],
        "status": registration["status"],
        "name": registration["name"],
        "created_at": registration["created_at"],
    }


@router.get("/registrations", response_model=list[schemas.RegistrationAdminOut])
def list_registrations(
    tournament_id: int,
    status: RegistrationStatus | None = Query(default=None),
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    return repo.list_registrations(
        conn,
        tournament_id,
        status=status.value if status is not None else None,
    )


@router.post(
    "/registrations/{registration_id}/confirm",
    response_model=schemas.RegistrationConfirmResult,
)
def confirm_registration(
    tournament_id: int,
    registration_id: int,
    conn: Connection = Depends(get_db),
    access=Depends(require_tournament_write),
):
    try:
        registration, player = registrations_service.confirm_registration(
            conn,
            tournament_id,
            registration_id,
            confirmed_by_user_id=int(access["user"]["id"]),
        )
    except registrations_service.RegistrationError as exc:
        raise _registration_http(exc) from None
    return {"registration": registration, "player": player}


@router.get("/organization", response_model=schemas.OrganizationOut)
def get_organization(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    organization = repo.get_organization(conn, tournament_id)
    if organization is None:
        raise _missing("ORGANIZATION_NOT_FOUND", "赛事组织方信息尚未设置")
    return organization


@router.put("/organization", response_model=schemas.OrganizationOut)
def upsert_organization(
    tournament_id: int,
    payload: schemas.OrganizationUpsert,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        with write_transaction(conn, busy_message="组织方信息繁忙，请稍后重试"):
            return repo.upsert_organization(
                conn,
                tournament_id,
                name=payload.name,
                contact_name=payload.contact_name,
                contact=payload.contact,
                note=payload.note,
            )
    except TransactionBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "TRANSACTION_BUSY", "message": str(exc)},
        ) from None


@router.get("/venue", response_model=schemas.VenueOut)
def get_venue(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_read),
):
    venue = repo.get_venue(conn, tournament_id)
    if venue is None:
        raise _missing("VENUE_NOT_FOUND", "赛事场馆信息尚未设置")
    return venue


@router.put("/venue", response_model=schemas.VenueOut)
def upsert_venue(
    tournament_id: int,
    payload: schemas.VenueUpsert,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_write),
):
    try:
        with write_transaction(conn, busy_message="场馆信息繁忙，请稍后重试"):
            return repo.upsert_venue(
                conn,
                tournament_id,
                name=payload.name,
                address=payload.address,
                contact_name=payload.contact_name,
                contact=payload.contact,
                note=payload.note,
            )
    except TransactionBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "TRANSACTION_BUSY", "message": str(exc)},
        ) from None
