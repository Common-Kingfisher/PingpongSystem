"""A2.5：真实赛事路由的统一鉴权接入。"""

from __future__ import annotations

import re

from app import db as db_module
from app import repository as repo
from app.main import app
from app.models import SystemRole, TournamentRole
from app.security import hash_password
from app.services import auth as auth_service


RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
PASSWORD = "StrongPassword123"
FORBIDDEN_EVENT_ADMIN = {"code": "FORBIDDEN", "message": "需要赛事管理员权限"}
MANAGEMENT_WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})
MANAGEMENT_WRITE_PREFIXES = ("/api/tournaments", "/api/matches")
PUBLIC_REGISTRATION_WRITES = frozenset({("POST", "/api/tournaments/{tournament_id}/registrations")})
TOURNAMENT_PAYLOAD = {
    "name": "A2.5 鉴权赛事",
    "date": "2026-09-21",
    "table_count": 3,
    "group_count": 1,
    "qualify_per_group": 1,
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_user_and_token(username: str, system_role: str) -> tuple[dict, str]:
    conn = db_module.connect()
    try:
        user = repo.create_user(
            conn,
            username,
            "鉴权测试用户",
            hash_password(PASSWORD, iterations=1000),
            system_role,
        )
        conn.commit()
        session = auth_service.login(conn, username, PASSWORD)
        return user, session["access_token"]
    finally:
        conn.close()


def _create_event_admin(username: str) -> tuple[dict, str]:
    return _create_user_and_token(username, SystemRole.EVENT_ADMIN.value)


def _management_write_operations() -> list[tuple[str, str]]:
    """从 OpenAPI 读取全部赛事管理写操作，避免只抽样验证部分路由。"""
    operations: list[tuple[str, str]] = []
    for path, path_spec in app.openapi()["paths"].items():
        if not path.startswith(MANAGEMENT_WRITE_PREFIXES):
            continue
        for method in path_spec:
            if method.lower() not in MANAGEMENT_WRITE_METHODS:
                continue
            if (method.upper(), path) in PUBLIC_REGISTRATION_WRITES:
                continue
            resolved_path = re.sub(r"\{[^}]+\}", "1", path)
            operations.append((method.upper(), resolved_path))
    return operations


def _assert_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == RESOURCE_NOT_FOUND


def test_all_tournament_writes_require_login(client):
    operations = _management_write_operations()
    assert len(operations) == 47

    client.headers.pop("Authorization")
    failures = []
    for method, path in operations:
        response = client.request(method, path, json={})
        if response.status_code != 401:
            failures.append((method, path, response.status_code, response.text))
            continue
        if response.json()["detail"]["code"] != "AUTH_REQUIRED":
            failures.append((method, path, response.status_code, response.text))

    assert not failures, failures


def test_system_admin_cannot_create_tournament(client):
    _, token = _create_user_and_token(
        "a25-system-admin", SystemRole.SYSTEM_ADMIN.value
    )
    response = client.post(
        "/api/tournaments",
        json=TOURNAMENT_PAYLOAD,
        headers=_headers(token),
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == FORBIDDEN_EVENT_ADMIN


def test_event_admin_create_sets_owner_and_owner_grant_with_tables(client, conn):
    current_user = client.get("/api/v1/auth/me").json()["user"]
    response = client.post("/api/tournaments", json=TOURNAMENT_PAYLOAD)

    assert response.status_code == 201, response.text
    tournament = response.json()

    persisted = repo.get_tournament(conn, tournament["id"])
    assert persisted["owner_user_id"] == current_user["id"]
    owner = conn.execute(
        "SELECT role, created_by_user_id, revoked_at FROM tournament_admins "
        "WHERE tournament_id = ? AND user_id = ?",
        (tournament["id"], current_user["id"]),
    ).fetchone()
    assert owner is not None
    assert owner["role"] == TournamentRole.OWNER.value
    assert owner["created_by_user_id"] == current_user["id"]
    assert owner["revoked_at"] is None
    assert len(repo.list_tables(conn, tournament["id"])) == TOURNAMENT_PAYLOAD["table_count"]


def test_other_event_admin_can_public_read_but_not_access_sensitive_or_write(
    client, conn
):
    owned = client.post("/api/tournaments", json=TOURNAMENT_PAYLOAD).json()
    _, token = _create_event_admin("second-event-admin")
    headers = _headers(token)

    public_read = client.get(
        f"/api/tournaments/{owned['id']}", headers=headers
    )
    assert public_read.status_code == 200, public_read.text
    assert public_read.json()["id"] == owned["id"]

    responses = (
        client.get(f"/api/tournaments/{owned['id']}/export", headers=headers),
        client.post(
            f"/api/tournaments/{owned['id']}/players",
            json={"name": "越权写入"},
            headers=headers,
        ),
        client.delete(
            f"/api/tournaments/{owned['id']}",
            params={"confirm_name": owned["name"]},
            headers=headers,
        ),
    )
    for response in responses:
        _assert_not_found(response)

    assert client.get("/api/tournaments", headers=headers).json() == []
    assert repo.get_tournament(conn, owned["id"]) is not None


def test_match_routes_resolve_parent_tournament_for_authorization(client, conn):
    owned = client.post("/api/tournaments", json=TOURNAMENT_PAYLOAD).json()
    match = repo.create_match(
        conn,
        owned["id"],
        "GROUP",
        None,
        1,
        1,
        None,
        None,
    )
    conn.commit()
    _, token = _create_event_admin("match-outsider")
    headers = _headers(token)
    payload = {"player_a_score": 2, "player_b_score": 1}

    _assert_not_found(
        client.post(f"/api/matches/{match['id']}/score", json=payload, headers=headers)
    )
    _assert_not_found(
        client.get(f"/api/matches/{match['id']}/score-audits", headers=headers)
    )
    _assert_not_found(client.get("/api/matches/999999/score-audits", headers=headers))
    assert client.get(f"/api/matches/{match['id']}/score-audits").status_code == 200
