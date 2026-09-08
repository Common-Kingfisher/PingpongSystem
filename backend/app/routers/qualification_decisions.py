"""主裁判人工晋级裁定路由。"""

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException

from .. import schemas
from ..db import get_db
from ..services import qualification_decisions as decision_service

router = APIRouter(
    prefix="/api/tournaments/{tournament_id}/groups/{group_id}",
    tags=["qualification-decisions"],
)


def _http(exc: decision_service.QualificationDecisionError) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=str(exc))


@router.post(
    "/qualification-decision",
    response_model=schemas.QualificationDecisionOut,
    status_code=201,
)
def create_decision(
    tournament_id: int,
    group_id: int,
    body: schemas.QualificationDecisionCreate,
    conn: Connection = Depends(get_db),
):
    try:
        return decision_service.create_decision(
            conn,
            tournament_id,
            group_id,
            body.selected_entry_ids,
            body.reason,
            body.operator_name,
        )
    except decision_service.QualificationDecisionError as exc:
        raise _http(exc)


@router.post(
    "/qualification-decision/revoke",
    response_model=schemas.QualificationDecisionOut,
)
def revoke_decision(
    tournament_id: int,
    group_id: int,
    body: schemas.QualificationDecisionRevoke,
    conn: Connection = Depends(get_db),
):
    try:
        return decision_service.revoke_decision(
            conn, tournament_id, group_id, body.reason, body.operator_name
        )
    except decision_service.QualificationDecisionError as exc:
        raise _http(exc)


@router.get(
    "/qualification-decisions",
    response_model=list[schemas.QualificationDecisionOut],
)
def list_decisions(
    tournament_id: int, group_id: int, conn: Connection = Depends(get_db)
):
    try:
        return decision_service.list_decisions(conn, tournament_id, group_id)
    except decision_service.QualificationDecisionError as exc:
        raise _http(exc)
