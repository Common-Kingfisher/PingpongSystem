"""A2.3 认证路由依赖：凭据解析与系统角色校验。

赛事级资源授权在 A2.4 中实现；本模块只包含认证 API 和系统用户 API
自身需要的最小依赖，避免 A2.3 反向依赖后续工作包。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlite3 import Connection

from .db import get_db
from .models import SystemRole
from .services import auth as auth_service


@dataclass(frozen=True)
class AuthContext:
    user: dict[str, Any]
    session_id: int
    expires_at: str
    token: str


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _auth_required(message: str = "请先登录") -> HTTPException:
    return _error(401, "AUTH_REQUIRED", message)


def extract_session_token(request: Request) -> str | None:
    """同时读取 Cookie 与 Bearer；两者冲突时按未认证处理。"""
    cookie_token = request.cookies.get("pp_session")
    header = request.headers.get("Authorization")
    bearer_token: str | None = None
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise _auth_required("Authorization 凭据格式无效")
        bearer_token = value.strip()

    if cookie_token and bearer_token and cookie_token != bearer_token:
        raise _auth_required("请求携带了冲突的登录凭据")
    return bearer_token or cookie_token


def get_current_user(
    request: Request, conn: Connection = Depends(get_db)
) -> AuthContext:
    token = extract_session_token(request)
    if not token:
        raise _auth_required()
    context = auth_service.authenticate_session(conn, token)
    if context is None:
        raise _auth_required("登录状态已失效，请重新登录")
    return AuthContext(
        user=context["user"],
        session_id=context["session_id"],
        expires_at=context["expires_at"],
        token=context["token"],
    )


def require_system_admin(
    context: AuthContext = Depends(get_current_user),
) -> AuthContext:
    if context.user["system_role"] != SystemRole.SYSTEM_ADMIN.value:
        raise _error(403, "FORBIDDEN", "需要系统管理员权限")
    return context
