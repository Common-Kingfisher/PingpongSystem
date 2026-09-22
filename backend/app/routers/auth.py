"""认证 API：登录、退出、当前用户和改密。"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import schemas
from ..db import get_db
from ..auth_dependencies import AuthContext, extract_session_token, get_current_user
from ..openapi_contract import (
    CLEAR_SESSION_COOKIE_HEADER,
    SET_SESSION_COOKIE_HEADER,
    error_response,
)
from ..services import auth as auth_service


SESSION_COOKIE_NAME = "pp_session"

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _auth_http(exc: auth_service.AuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _set_session_cookie(
    response: Response, request: Request, token: str, expires_at: str
) -> None:
    expires = datetime.fromisoformat(expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    max_age = max(0, int((expires - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=expires,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=False,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/login",
    response_model=schemas.AuthLoginResponse,
    response_model_exclude_none=True,
    responses={
        200: {
            "description": "登录成功；browser 设置 Cookie，bearer 返回 access_token。",
            "headers": {"Set-Cookie": SET_SESSION_COOKIE_HEADER},
        },
        401: error_response(
            "用户名、密码或账号状态错误。",
            codes=["AUTH_INVALID_CREDENTIALS"],
            example_message="用户名或密码错误",
        ),
    },
    openapi_extra={
        "x-auth-modes": ["browser", "bearer"],
        "x-credential-conflict": {"status": 401, "code": "AUTH_REQUIRED"},
    },
)
def login(
    payload: schemas.AuthLoginRequest,
    request: Request,
    response: Response,
    conn: Connection = Depends(get_db),
):
    try:
        result = auth_service.login(conn, payload.username.strip(), payload.password)
    except auth_service.AuthError as exc:
        raise _auth_http(exc)

    if payload.mode == "browser":
        _set_session_cookie(response, request, result["access_token"], result["expires_at"])
        access_token = None
    else:
        access_token = result["access_token"]

    return schemas.AuthLoginResponse(
        access_token=access_token,
        token_type="Bearer" if access_token else None,
        expires_at=result["expires_at"],
        user=schemas.AuthUserOut(**result["user"]),
    )


@router.post(
    "/logout",
    status_code=204,
    responses={
        204: {
            "description": "退出成功或幂等成功；成功时删除 pp_session Cookie。",
            "headers": {"Set-Cookie": CLEAR_SESSION_COOKIE_HEADER},
        },
        401: error_response(
            "Cookie 与 Bearer 指向不同会话，或 Authorization 格式无效。",
            codes=["AUTH_REQUIRED"],
            example_message="请求携带了冲突的登录凭据",
        ),
    },
    openapi_extra={
        "x-auth-behavior": {
            "credentials": "optional",
            "accepted": ["sessionCookie", "bearerAuth"],
            "idempotent_without_valid_credentials": True,
            "credential_conflict": {"status": 401, "code": "AUTH_REQUIRED"},
        }
    },
)
def logout(
    request: Request,
    response: Response,
    conn: Connection = Depends(get_db),
) -> None:
    """撤销当前凭据对应的 Session；无凭据或重复退出均保持幂等。"""
    token = extract_session_token(request)
    auth_service.logout(conn, token)
    _clear_session_cookie(response)


@router.get(
    "/me",
    response_model=schemas.AuthMeResponse,
    responses={
        401: error_response(
            "未登录、凭据冲突、会话过期、撤销或账号停用。",
            codes=["AUTH_REQUIRED"],
            example_message="请先登录",
        ),
    },
)
def me(
    context: AuthContext = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    return schemas.AuthMeResponse(
        user=schemas.AuthUserOut(**auth_service.public_user(context.user)),
        tournament_access_count=auth_service.count_tournament_access(
            conn, context.user["id"]
        ),
    )


@router.post(
    "/change-password",
    status_code=204,
    responses={
        204: {
            "description": "改密成功并撤销该用户全部旧会话，同时删除当前 Cookie。",
            "headers": {"Set-Cookie": CLEAR_SESSION_COOKIE_HEADER},
        },
        401: error_response(
            "未登录、会话失效或当前密码错误。",
            codes=["AUTH_REQUIRED", "AUTH_INVALID_CREDENTIALS"],
            example_code="AUTH_INVALID_CREDENTIALS",
            example_message="当前密码错误",
        ),
    },
    openapi_extra={
        "x-business-error-codes": {"422": ["INVALID_NEW_PASSWORD"]},
    },
)
def change_password(
    payload: schemas.AuthChangePasswordRequest,
    response: Response,
    context: AuthContext = Depends(get_current_user),
    conn: Connection = Depends(get_db),
) -> None:
    try:
        auth_service.change_password(
            conn,
            user_id=context.user["id"],
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except auth_service.AuthError as exc:
        raise _auth_http(exc)
    _clear_session_cookie(response)
