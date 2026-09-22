"""赛事协作管理员授权 API。"""

from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException

from .. import schemas
from ..db import get_db
from ..dependencies import require_tournament_admin_management
from ..openapi_contract import error_response
from ..services import tournament_admins as admin_service


router = APIRouter(
    prefix="/api/tournaments/{tournament_id}/admins",
    tags=["tournament-admins"],
)


def _http(exc: admin_service.TournamentAdminError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


_AUTH_AND_NOT_FOUND_RESPONSES = {
    401: error_response(
        "未登录、凭据冲突或会话失效。",
        codes=["AUTH_REQUIRED"],
        example_message="请先登录",
    ),
    404: error_response(
        "赛事不存在，或当前用户没有该赛事授权管理权限。",
        codes=["RESOURCE_NOT_FOUND"],
        example_message="资源不存在",
    ),
}


@router.get(
    "",
    response_model=list[schemas.TournamentAdminOut],
    responses=_AUTH_AND_NOT_FOUND_RESPONSES,
    openapi_extra={
        "x-permission": "tournament OWNER or ADMIN only",
        "x-owner-source": "tournaments.owner_user_id",
    },
)
def list_tournament_admins(
    tournament_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_admin_management),
):
    try:
        return admin_service.list_tournament_admins(conn, tournament_id)
    except admin_service.TournamentAdminError as exc:
        raise _http(exc)


@router.post(
    "",
    response_model=schemas.TournamentAdminOut,
    responses={
        **_AUTH_AND_NOT_FOUND_RESPONSES,
        409: error_response(
            "赛事 Owner 只能由 tournaments.owner_user_id 表示，不能通过普通授权接口变更。",
            codes=["OWNER_PROTECTED"],
            example_message="赛事 Owner 不能通过此接口变更",
        ),
    },
    openapi_extra={
        "x-permission": "tournament OWNER or ADMIN only",
        "x-grantable-roles": ["ADMIN", "OPERATOR", "VIEWER"],
        "x-target-requirements": "active EVENT_ADMIN user",
        "x-business-error-codes": {"422": ["INVALID_TOURNAMENT_ROLE"]},
    },
)
def grant_tournament_admin(
    tournament_id: int,
    payload: schemas.TournamentAdminGrantRequest,
    conn: Connection = Depends(get_db),
    access=Depends(require_tournament_admin_management),
):
    try:
        return admin_service.grant_tournament_admin(
            conn,
            tournament_id=tournament_id,
            user_id=payload.user_id,
            role=payload.role,
            actor_user_id=int(access["user"]["id"]),
        )
    except admin_service.TournamentAdminError as exc:
        raise _http(exc)


@router.delete(
    "/{user_id}",
    status_code=204,
    responses={
        **_AUTH_AND_NOT_FOUND_RESPONSES,
        409: error_response(
            "赛事 Owner 不能通过普通授权接口撤销。",
            codes=["OWNER_PROTECTED"],
            example_message="赛事 Owner 不能通过此接口变更",
        ),
    },
    openapi_extra={
        "x-permission": "tournament OWNER or ADMIN only",
        "x-idempotent": True,
        "x-owner-source": "tournaments.owner_user_id",
    },
)
def revoke_tournament_admin(
    tournament_id: int,
    user_id: int,
    conn: Connection = Depends(get_db),
    _access=Depends(require_tournament_admin_management),
):
    try:
        admin_service.revoke_tournament_admin(
            conn,
            tournament_id=tournament_id,
            user_id=user_id,
        )
    except admin_service.TournamentAdminError as exc:
        raise _http(exc)
