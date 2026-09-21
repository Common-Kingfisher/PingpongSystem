"""系统初始化与系统用户 API。"""

from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import schemas
from ..db import get_db
from ..auth_dependencies import AuthContext, require_system_admin
from ..services import auth as auth_service


LOCAL_BOOTSTRAP_HOSTS = frozenset(
    {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}
)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _auth_http(exc: auth_service.AuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def require_local_bootstrap_client(request: Request) -> None:
    """Bootstrap 写入口只认 socket 对端地址，不信任代理转发头。"""
    client = request.client
    host = client.host.lower() if client and client.host else ""
    if host not in LOCAL_BOOTSTRAP_HOSTS:
        raise HTTPException(
            status_code=404,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"},
        )


@router.get(
    "/bootstrap/status",
    response_model=schemas.BootstrapStatusResponse,
)
def bootstrap_status(conn: Connection = Depends(get_db)):
    try:
        status = auth_service.get_bootstrap_status(conn)
    except auth_service.AuthError as exc:
        raise _auth_http(exc)
    return schemas.BootstrapStatusResponse(status=status)


@router.post(
    "/bootstrap",
    response_model=schemas.BootstrapResponse,
    status_code=201,
    dependencies=[Depends(require_local_bootstrap_client)],
)
def bootstrap(
    payload: schemas.BootstrapRequest,
    conn: Connection = Depends(get_db),
):
    try:
        user = auth_service.bootstrap(
            conn,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            phone=payload.phone,
            note=payload.note,
        )
    except auth_service.AuthError as exc:
        raise _auth_http(exc)
    return schemas.BootstrapResponse(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        system_role=user["system_role"],
    )


@router.post(
    "/users",
    response_model=schemas.EventAdminOut,
    status_code=201,
)
def create_event_admin(
    payload: schemas.EventAdminCreateRequest,
    _: AuthContext = Depends(require_system_admin),
    conn: Connection = Depends(get_db),
):
    try:
        user = auth_service.create_event_admin(
            conn,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            phone=payload.phone,
            note=payload.note,
        )
    except auth_service.AuthError as exc:
        raise _auth_http(exc)
    return schemas.EventAdminOut(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        system_role=user["system_role"],
        phone=user.get("phone"),
        note=user.get("note"),
    )
