"""D2 A2.3：认证 API、Cookie 与 Session 边界。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app import repository as repo
from app.main import app
from app.models import SystemRole
from app.security import hash_password, hash_session_token


PASSWORD = "StrongPassword123"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "auth-api.db"))
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    db_module.init_db()
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def _create_user(username: str = "event-admin") -> dict:
    conn = db_module.connect()
    try:
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
    finally:
        conn.close()


def _login(client: TestClient, mode: str = "bearer", username: str = "event-admin"):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD, "mode": mode},
    )


def test_browser_login_sets_http_only_session_cookie(client):
    _create_user()

    response = _login(client, mode="browser")

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "pp_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "access_token" not in response.json()
    assert "token_type" not in response.json()
    assert client.cookies.get("pp_session")


def test_https_browser_login_adds_secure_cookie(client):
    _create_user()

    with TestClient(
        app,
        base_url="https://testserver",
        client=("127.0.0.1", 50000),
    ) as secure_client:
        response = _login(secure_client, mode="browser")

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_bearer_login_returns_token_and_stores_only_hash(client):
    user = _create_user()

    response = _login(client, mode="bearer")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    payload = response.json()
    assert payload["token_type"] == "Bearer"
    assert payload["access_token"]
    assert payload["user"] == {
        "id": user["id"],
        "username": "event-admin",
        "display_name": "赛事管理员",
        "system_role": "EVENT_ADMIN",
    }
    assert "password_hash" not in payload["user"]

    conn = db_module.connect()
    try:
        row = conn.execute(
            "SELECT token_hash FROM user_sessions WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row["token_hash"] == hash_session_token(payload["access_token"])
    assert row["token_hash"] != payload["access_token"]


def test_login_failures_use_same_stable_error(client):
    user = _create_user("inactive-user")
    conn = db_module.connect()
    try:
        repo.set_user_active(conn, user["id"], False)
        conn.commit()
    finally:
        conn.close()

    cases = (
        ("unknown-user", PASSWORD),
        ("inactive-user", PASSWORD),
        ("event-admin", "WrongPassword123"),
    )
    for username, password in cases:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password, "mode": "bearer"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == {
            "code": "AUTH_INVALID_CREDENTIALS",
            "message": "用户名或密码错误",
        }


def test_me_requires_login_and_does_not_expose_sensitive_fields(client):
    unauthenticated = client.get("/api/v1/auth/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"

    _create_user()
    login = _login(client)
    token = login.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tournament_access_count"] == 0
    assert payload["user"]["username"] == "event-admin"
    assert "password_hash" not in response.text
    assert "token_hash" not in response.text
    assert "phone" not in payload["user"]
    assert "note" not in payload["user"]


def test_change_password_revokes_old_session_and_accepts_new_password(client):
    _create_user()
    token = _login(client).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": PASSWORD,
            "new_password": "NewStrongPassword456",
        },
    )

    assert response.status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert _login(client).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={
            "username": "event-admin",
            "password": "NewStrongPassword456",
            "mode": "bearer",
        },
    ).status_code == 200


def test_logout_is_idempotent_and_revokes_bearer_session(client):
    _create_user()
    token = _login(client).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_conflicting_cookie_and_bearer_credentials_are_rejected(client):
    _create_user()
    assert _login(client, mode="browser").status_code == 200
    bearer = _login(client, mode="bearer")
    token = bearer.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_deactivation_invalidates_existing_bearer_session(client):
    user = _create_user()
    token = _login(client).json()["access_token"]
    conn = db_module.connect()
    try:
        repo.set_user_active(conn, user["id"], False)
        conn.commit()
    finally:
        conn.close()

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_deactivation_invalidates_existing_browser_session(client):
    user = _create_user()
    assert _login(client, mode="browser").status_code == 200
    conn = db_module.connect()
    try:
        repo.set_user_active(conn, user["id"], False)
        conn.commit()
    finally:
        conn.close()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_logout_without_credentials_is_idempotent(client):
    client.cookies.clear()

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_logout_rejects_conflicting_cookie_and_bearer_credentials(client):
    _create_user()
    assert _login(client, mode="browser").status_code == 200
    cookie_token = client.cookies.get("pp_session")
    bearer_token = _login(client, mode="bearer").json()["access_token"]

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {bearer_token}"},
        cookies={"pp_session": cookie_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "code": "AUTH_REQUIRED",
        "message": "请求携带了冲突的登录凭据",
    }

    conn = db_module.connect()
    try:
        sessions = conn.execute(
            "SELECT revoked_at FROM user_sessions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert len(sessions) == 2
    assert all(session["revoked_at"] is None for session in sessions)

def test_lan_client_auth_and_role_checks_do_not_depend_on_ip(client):
    """Patch P-01：LAN 仅改变传输路径，不改变认证和系统角色判定。"""
    _create_user()

    with TestClient(
        app,
        client=("192.168.50.10", 50000),
    ) as lan_client:
        assert lan_client.get("/api/health").status_code == 200

        login = _login(lan_client)
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert lan_client.get("/api/v1/auth/me", headers=headers).status_code == 200

        forbidden = lan_client.post(
            "/api/v1/system/users",
            headers=headers,
            json={
                "username": "lan-created",
                "display_name": "不应创建",
                "password": "StrongPassword123",
            },
        )

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "FORBIDDEN"
