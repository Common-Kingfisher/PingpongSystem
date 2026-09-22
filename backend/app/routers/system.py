"""系统初始化与系统用户 API。"""

from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import schemas
from ..db import get_db
from ..auth_dependencies import AuthContext, require_system_admin
from ..openapi_contract import error_response
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
    responses={
        500: error_response(
            "数据库初始化状态异常。",
            codes=["SYSTEM_STATE_MISSING"],
            example_message="系统初始化状态缺失",
        ),
    },
    openapi_extra={
        "x-bootstrap-status-states": [
            "NEEDS_INITIALIZATION",
            "READY",
            "RECOVERY_REQUIRED",
        ],
        "x-bootstrap-write-endpoint": "/api/v1/system/bootstrap",
    },
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
    responses={
        404: error_response(
            "非服务器本机访问 Web bootstrap，统一伪装为资源不存在。",
            codes=["RESOURCE_NOT_FOUND"],
            example_message="资源不存在",
        ),
        409: error_response(
            "系统已完成初始化或需要本机恢复，或用户名冲突。",
            codes=[
                "BOOTSTRAP_ALREADY_COMPLETED",
                "RECOVERY_REQUIRED",
                "USERNAME_ALREADY_EXISTS",
            ],
            example_message="系统已经完成初始化",
        ),
    },
    openapi_extra={
        "x-local-only": True,
        "x-local-detection": "request.client.host; proxy headers are ignored",
        "x-non-local-status": 404,
        "x-non-local-code": "RESOURCE_NOT_FOUND",
        "x-business-error-codes": {
            "422": ["INVALID_BOOTSTRAP_INPUT", "INVALID_BOOTSTRAP_PASSWORD"],
            "500": ["SYSTEM_STATE_MISSING", "SYSTEM_STATE_ERROR"],
        },
    },
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
    responses={
        401: error_response(
            "未登录、凭据冲突或会话失效。",
            codes=["AUTH_REQUIRED"],
            example_message="请先登录",
        ),
        403: error_response(
            "当前系统角色不是 SYSTEM_ADMIN。",
            codes=["FORBIDDEN"],
            example_message="需要系统管理员权限",
        ),
        409: error_response(
            "用户名已存在，用户名比较大小写不敏感。",
            codes=["USERNAME_ALREADY_EXISTS"],
            example_message="用户名已存在",
        ),
    },
    openapi_extra={
        "x-business-error-codes": {
            "422": ["INVALID_EVENT_ADMIN_INPUT", "INVALID_EVENT_ADMIN_PASSWORD"],
        },
        "x-permission": "SYSTEM_ADMIN only; created EVENT_ADMIN receives no tournament access",
    },
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
