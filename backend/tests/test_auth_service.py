"""D2 A2.2：登录、Session 与账号状态服务。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import repository as repo
from app.models import SystemRole
from app.security import hash_password, hash_session_token
from app.services import auth as auth_service


PASSWORD = "StrongPassword123"


def _create_event_admin(conn, username="event-admin"):
    user = repo.create_user(
        conn,
        username,
        "赛事管理员",
        hash_password(PASSWORD, iterations=1000),
        SystemRole.EVENT_ADMIN.value,
        phone="13800000000",
        note="测试账号",
    )
    conn.commit()
    return user


def test_login_stores_only_token_hash_and_returns_public_user(conn):
    user = _create_event_admin(conn)

    result = auth_service.login(conn, "event-admin", PASSWORD)

    stored = conn.execute(
        "SELECT token_hash FROM user_sessions WHERE user_id = ?", (user["id"],)
    ).fetchone()
    assert stored["token_hash"] == hash_session_token(result["access_token"])
    assert stored["token_hash"] != result["access_token"]
    assert "password_hash" not in result["user"]
    assert "phone" not in result["user"]
    assert "note" not in result["user"]

    context = auth_service.authenticate_session(conn, result["access_token"])
    assert context is not None
    assert context["user"]["id"] == user["id"]


def test_inactive_user_cannot_login(conn):
    user = _create_event_admin(conn, username="inactive-user")
    repo.set_user_active(conn, user["id"], False)
    conn.commit()

    with pytest.raises(auth_service.AuthError) as exc_info:
        auth_service.login(conn, "inactive-user", PASSWORD)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AUTH_INVALID_CREDENTIALS"


def test_deactivation_revokes_existing_session_and_invalidates_token(conn):
    user = _create_event_admin(conn, username="disabled-session")
    login = auth_service.login(conn, "disabled-session", PASSWORD)
    assert auth_service.authenticate_session(conn, login["access_token"]) is not None

    auth_service.set_user_active(conn, user_id=user["id"], active=False)

    assert auth_service.authenticate_session(conn, login["access_token"]) is None
    stored = conn.execute(
        "SELECT revoked_at FROM user_sessions WHERE user_id = ?", (user["id"],)
    ).fetchone()
    assert stored["revoked_at"] is not None


def test_expired_and_logged_out_sessions_are_rejected(conn):
    _create_event_admin(conn, username="session-lifecycle")

    first = auth_service.login(conn, "session-lifecycle", PASSWORD)
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute(
        "UPDATE user_sessions SET expires_at = ? WHERE token_hash = ?",
        (expired_at, hash_session_token(first["access_token"])),
    )
    conn.commit()
    assert auth_service.authenticate_session(conn, first["access_token"]) is None

    second = auth_service.login(conn, "session-lifecycle", PASSWORD)
    auth_service.logout(conn, second["access_token"])
    assert auth_service.authenticate_session(conn, second["access_token"]) is None
    auth_service.logout(conn, second["access_token"])


def test_change_password_revokes_all_old_sessions(conn):
    user = _create_event_admin(conn, username="password-change")
    first = auth_service.login(conn, "password-change", PASSWORD)
    second = auth_service.login(conn, "password-change", PASSWORD)

    auth_service.change_password(
        conn,
        user_id=user["id"],
        current_password=PASSWORD,
        new_password="NewStrongPassword456",
    )

    assert auth_service.authenticate_session(conn, first["access_token"]) is None
    assert auth_service.authenticate_session(conn, second["access_token"]) is None
    with pytest.raises(auth_service.AuthError):
        auth_service.login(conn, "password-change", PASSWORD)
    assert auth_service.login(conn, "password-change", "NewStrongPassword456")
