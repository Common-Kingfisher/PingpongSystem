"""认证服务：登录、Session 校验、退出和改密。"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

from .. import repository as repo
from ..models import BootstrapStatus, SystemRole
from ..security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    validate_password_strength,
    verify_password,
)


DEFAULT_SESSION_HOURS = 12


class AuthError(RuntimeError):
    """认证业务错误，由 Router 转换成稳定 JSON 错误。"""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _session_hours() -> int:
    raw = os.environ.get("AUTH_SESSION_HOURS", str(DEFAULT_SESSION_HOURS))
    try:
        hours = int(raw)
    except ValueError as exc:
        raise AuthError(500, "SERVER_CONFIG_ERROR", "会话时长配置无效") from exc
    if hours < 1:
        raise AuthError(500, "SERVER_CONFIG_ERROR", "会话时长必须大于 0")
    return hours


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def public_user(user: dict) -> dict:
    """只暴露业务需要的用户字段，避免哈希和内部字段泄漏。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "system_role": user["system_role"],
    }


def login(conn: sqlite3.Connection, username: str, password: str) -> dict:
    user = repo.get_user_by_username(conn, username)
    if (
        user is None
        or not bool(user["active"])
        or not verify_password(password, user.get("password_hash"))
    ):
        raise AuthError(401, "AUTH_INVALID_CREDENTIALS", "用户名或密码错误")

    token = generate_session_token()
    expires_at = _utc_now() + timedelta(hours=_session_hours())
    session = repo.create_user_session(
        conn, user["id"], hash_session_token(token), expires_at.isoformat()
    )
    conn.commit()
    return {
        "access_token": token,
        "expires_at": session["expires_at"],
        "user": public_user(user),
    }


def authenticate_session(conn: sqlite3.Connection, token: str | None) -> dict | None:
    """解析 Token 并返回用户与 Session；无效、过期、撤销、停用均返回 None。"""
    if not token:
        return None
    session = repo.get_user_session_by_token_hash(conn, hash_session_token(token))
    if session is None or session["revoked_at"] is not None or not bool(session["active"]):
        return None
    if _parse_utc(session["expires_at"]) <= _utc_now():
        return None

    repo.touch_user_session(conn, session["session_id"])
    conn.commit()
    user = {
        "id": session["user_id"],
        "username": session["username"],
        "display_name": session["display_name"],
        "password_hash": session["password_hash"],
        "system_role": session["system_role"],
        "active": session["active"],
        "created_at": session["user_created_at"],
        "updated_at": session["user_updated_at"],
    }
    return {
        "user": user,
        "session_id": session["session_id"],
        "expires_at": session["expires_at"],
        "token": token,
    }


def logout(conn: sqlite3.Connection, token: str | None) -> None:
    """撤销当前 Session；重复退出和未知 Token 都保持幂等。"""
    if token:
        repo.revoke_user_session_by_hash(conn, hash_session_token(token))
        conn.commit()


def change_password(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    current_password: str,
    new_password: str,
) -> None:
    user = repo.get_user_by_id(conn, user_id)
    if user is None or not verify_password(current_password, user.get("password_hash")):
        raise AuthError(401, "AUTH_INVALID_CREDENTIALS", "当前密码错误")
    try:
        validate_password_strength(new_password)
    except ValueError as exc:
        raise AuthError(422, "INVALID_NEW_PASSWORD", str(exc)) from exc

    repo.update_user_password(conn, user_id, hash_password(new_password))
    repo.revoke_user_sessions(conn, user_id)
    conn.commit()


def get_bootstrap_status(conn: sqlite3.Connection) -> str:
    """返回冻结的三种初始化状态，不把管理员数量作为 Web 入口开关。"""
    completed = repo.get_bootstrap_completed(conn)
    if completed is None:
        raise AuthError(500, "SYSTEM_STATE_MISSING", "系统初始化状态缺失")
    if not completed:
        return BootstrapStatus.NEEDS_INITIALIZATION.value
    if repo.has_active_system_admin(conn):
        return BootstrapStatus.READY.value
    return BootstrapStatus.RECOVERY_REQUIRED.value


def bootstrap(
    conn: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    phone: str | None = None,
    note: str | None = None,
) -> dict:
    """原子创建首个 SYSTEM_ADMIN 并关闭 Web bootstrap。"""
    normalized_username = username.strip()
    normalized_display_name = display_name.strip()
    if not normalized_username:
        raise AuthError(422, "INVALID_BOOTSTRAP_INPUT", "用户名不能为空")
    if not normalized_display_name:
        raise AuthError(422, "INVALID_BOOTSTRAP_INPUT", "显示名称不能为空")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise AuthError(422, "INVALID_BOOTSTRAP_PASSWORD", str(exc)) from exc

    if conn.in_transaction:
        raise AuthError(500, "SYSTEM_STATE_ERROR", "初始化连接已存在未提交事务")

    conn.execute("BEGIN IMMEDIATE")
    try:
        completed = repo.get_bootstrap_completed(conn)
        if completed is None:
            raise AuthError(500, "SYSTEM_STATE_MISSING", "系统初始化状态缺失")
        if completed:
            if repo.has_active_system_admin(conn):
                raise AuthError(
                    409,
                    "BOOTSTRAP_ALREADY_COMPLETED",
                    "系统已经完成初始化",
                )
            raise AuthError(
                409,
                "RECOVERY_REQUIRED",
                "系统需要本机恢复，Web 初始化入口已永久关闭",
            )

        user = repo.create_user(
            conn,
            normalized_username,
            normalized_display_name,
            hash_password(password),
            SystemRole.SYSTEM_ADMIN.value,
            phone=phone,
            note=note,
        )
        repo.mark_bootstrap_completed(conn)
        conn.commit()
        return public_user(user)
    except AuthError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "users.username" in str(exc):
            raise AuthError(409, "USERNAME_ALREADY_EXISTS", "用户名已存在") from exc
        raise
    except Exception:
        conn.rollback()
        raise


def set_user_active(
    conn: sqlite3.Connection, *, user_id: int, active: bool
) -> None:
    """更新账号状态；停用时在同一事务撤销其全部有效 Session。"""
    user = repo.get_user_by_id(conn, user_id)
    if user is None:
        raise AuthError(404, "USER_NOT_FOUND", "用户不存在")

    repo.set_user_active(conn, user_id, active)
    if not active:
        repo.revoke_user_sessions(conn, user_id)
    conn.commit()


def count_tournament_access(conn: sqlite3.Connection, user_id: int) -> int:
    return repo.count_tournament_access(conn, user_id)
