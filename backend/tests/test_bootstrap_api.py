"""D2 A2.3：Bootstrap 状态、本机边界与恢复状态 API。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app import repository as repo
from app.main import app


PASSWORD = "InitialAdmin123"


@pytest.fixture()
def local_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "bootstrap-api.db"))
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    db_module.init_db()
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client


def _payload(username: str = "system-admin") -> dict:
    return {
        "username": username,
        "display_name": "系统管理员",
        "password": PASSWORD,
        "phone": "13900000000",
        "note": "首次初始化",
    }


def test_local_bootstrap_succeeds_once_and_status_persists(local_client):
    status = local_client.get("/api/v1/system/bootstrap/status")
    assert status.status_code == 200
    assert status.json() == {"status": "NEEDS_INITIALIZATION"}

    created = local_client.post("/api/v1/system/bootstrap", json=_payload())

    assert created.status_code == 201
    assert created.json()["username"] == "system-admin"
    assert created.json()["system_role"] == "SYSTEM_ADMIN"
    assert "password_hash" not in created.text
    assert "access_token" not in created.text
    assert local_client.get("/api/v1/system/bootstrap/status").json() == {
        "status": "READY"
    }

    repeated = local_client.post(
        "/api/v1/system/bootstrap",
        json=_payload("second-admin"),
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "BOOTSTRAP_ALREADY_COMPLETED"

    conn = db_module.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    "remote_host",
    ("testclient", "192.168.1.10", "::ffff:192.168.1.10"),
)
def test_non_local_bootstrap_is_hidden_and_proxy_header_is_ignored(
    remote_host, tmp_path, monkeypatch
):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "remote-bootstrap.db"))
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")

    with TestClient(app, client=(remote_host, 50000)) as remote_client:
        response = remote_client.post(
            "/api/v1/system/bootstrap",
            json=_payload(),
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        status = remote_client.get("/api/v1/system/bootstrap/status")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "资源不存在",
    }
    assert status.json() == {"status": "NEEDS_INITIALIZATION"}


def test_recovery_required_never_reopens_web_bootstrap(local_client):
    created = local_client.post("/api/v1/system/bootstrap", json=_payload())
    user_id = created.json()["id"]
    conn = db_module.connect()
    try:
        repo.set_user_active(conn, user_id, False)
        conn.commit()
    finally:
        conn.close()

    assert local_client.get("/api/v1/system/bootstrap/status").json() == {
        "status": "RECOVERY_REQUIRED"
    }
    response = local_client.post(
        "/api/v1/system/bootstrap",
        json=_payload("recovery-admin"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RECOVERY_REQUIRED"
