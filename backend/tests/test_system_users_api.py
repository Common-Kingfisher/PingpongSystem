"""D2 A2.3：SYSTEM_ADMIN 创建 EVENT_ADMIN API。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app import repository as repo
from app.main import app


SYSTEM_PASSWORD = "InitialAdmin123"
EVENT_PASSWORD = "EventAdminPassword456"


@pytest.fixture()
def local_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "system-users-api.db"))
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    db_module.init_db()
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def _bootstrap_and_login(client: TestClient) -> str:
    created = client.post(
        "/api/v1/system/bootstrap",
        json={
            "username": "system-admin",
            "display_name": "系统管理员",
            "password": SYSTEM_PASSWORD,
            "phone": "13900000000",
            "note": "首次初始化",
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "system-admin",
            "password": SYSTEM_PASSWORD,
            "mode": "bearer",
        },
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def _event_admin_payload(username: str = "event-admin") -> dict:
    return {
        "username": username,
        "display_name": "赛事管理员",
        "password": EVENT_PASSWORD,
        "phone": "13800000000",
        "note": "D2 测试账号",
    }


def test_create_event_admin_requires_authentication(local_client):
    response = local_client.post(
        "/api/v1/system/users",
        json=_event_admin_payload(),
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_system_admin_creates_event_admin_without_sensitive_response(local_client):
    token = _bootstrap_and_login(local_client)
    response = local_client.post(
        "/api/v1/system/users",
        json=_event_admin_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["username"] == "event-admin"
    assert payload["display_name"] == "赛事管理员"
    assert payload["system_role"] == "EVENT_ADMIN"
    assert payload["phone"] == "13800000000"
    assert payload["note"] == "D2 测试账号"
    assert "password" not in response.text
    assert "password_hash" not in response.text
    assert "access_token" not in response.text
    assert "token_hash" not in response.text

    conn = db_module.connect()
    try:
        user = repo.get_user_by_username(conn, "event-admin")
        assert user["password_hash"] != EVENT_PASSWORD
        assert user["password_hash"].startswith("pbkdf2_sha256$")
        assert repo.count_tournament_access(conn, user["id"]) == 0
    finally:
        conn.close()


def test_event_admin_is_forbidden_and_can_have_optional_profile_fields(local_client):
    system_token = _bootstrap_and_login(local_client)
    payload = {
        "username": "event-admin",
        "display_name": "赛事管理员",
        "password": EVENT_PASSWORD,
    }
    created = local_client.post(
        "/api/v1/system/users",
        json=payload,
        headers={"Authorization": f"Bearer {system_token}"},
    )
    assert created.status_code == 201
    assert created.json()["phone"] is None
    assert created.json()["note"] is None

    event_login = local_client.post(
        "/api/v1/auth/login",
        json={
            "username": "event-admin",
            "password": EVENT_PASSWORD,
            "mode": "bearer",
        },
    )
    event_token = event_login.json()["access_token"]
    forbidden = local_client.post(
        "/api/v1/system/users",
        json=_event_admin_payload("another-admin"),
        headers={"Authorization": f"Bearer {event_token}"},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "FORBIDDEN"


def test_username_conflict_is_case_insensitive(local_client):
    token = _bootstrap_and_login(local_client)
    headers = {"Authorization": f"Bearer {token}"}
    assert local_client.post(
        "/api/v1/system/users",
        json=_event_admin_payload("Event-Admin"),
        headers=headers,
    ).status_code == 201

    duplicate = local_client.post(
        "/api/v1/system/users",
        json=_event_admin_payload("event-admin"),
        headers=headers,
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {
        "code": "USERNAME_ALREADY_EXISTS",
        "message": "用户名已存在",
    }


def test_event_admin_input_and_password_are_validated(local_client):
    token = _bootstrap_and_login(local_client)
    headers = {"Authorization": f"Bearer {token}"}

    weak_password = _event_admin_payload()
    weak_password["password"] = "aaaaaaaaaaaa"
    response = local_client.post(
        "/api/v1/system/users",
        json=weak_password,
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_EVENT_ADMIN_PASSWORD"

    blank_username = _event_admin_payload("   ")
    response = local_client.post(
        "/api/v1/system/users",
        json=blank_username,
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_EVENT_ADMIN_INPUT"
