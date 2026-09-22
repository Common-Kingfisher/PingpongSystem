"""D3A：赛事协作管理员最小授权闭环与异常结果权限反例。"""

from __future__ import annotations

import pytest

from app import repository as repo
from app.models import SystemRole, TournamentRole
from app.security import hash_password
from app.services import auth as auth_service


PASSWORD = "StrongPassword123"
RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
OWNER_PROTECTED = {"code": "OWNER_PROTECTED", "message": "赛事 Owner 不能通过此接口变更"}
INVALID_TOURNAMENT_ROLE = {"code": "INVALID_TOURNAMENT_ROLE", "message": "赛事角色无效"}
TOURNAMENT_PAYLOAD = {
    "name": "D3A 协作管理员赛事",
    "date": "2026-09-22",
    "table_count": 3,
    "group_count": 1,
    "qualify_per_group": 1,
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_user(
    conn,
    username: str,
    *,
    system_role: SystemRole = SystemRole.EVENT_ADMIN,
    active: bool = True,
) -> tuple[dict, str | None]:
    user = repo.create_user(
        conn,
        username,
        f"{username} 显示名",
        hash_password(PASSWORD, iterations=1000),
        system_role.value,
    )
    if not active:
        repo.set_user_active(conn, user["id"], False)
    conn.commit()
    token = None
    if active:
        token = auth_service.login(conn, username, PASSWORD)["access_token"]
    return user, token


def _create_tournament(client, name: str = TOURNAMENT_PAYLOAD["name"]) -> dict:
    response = client.post(
        "/api/tournaments",
        json={**TOURNAMENT_PAYLOAD, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _grant(conn, tournament_id: int, user_id: int, role: TournamentRole) -> None:
    repo.upsert_tournament_admin(
        conn,
        tournament_id,
        user_id,
        role.value,
        created_by_user_id=1,
    )
    conn.commit()


def _assert_not_found(response) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == RESOURCE_NOT_FOUND


def test_management_endpoints_require_login(client):
    tournament = _create_tournament(client)
    client.headers.pop("Authorization")

    responses = (
        client.get(f"/api/tournaments/{tournament['id']}/admins"),
        client.post(
            f"/api/tournaments/{tournament['id']}/admins",
            json={"user_id": 1, "role": "VIEWER"},
        ),
        client.delete(f"/api/tournaments/{tournament['id']}/admins/1"),
    )
    for response in responses:
        assert response.status_code == 401, response.text
        assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_owner_can_list_grant_update_revoke_and_restore(client, conn):
    tournament = _create_tournament(client)
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    target, _ = _create_user(conn, "d3a-owner-target")

    initial = client.get(f"/api/tournaments/{tournament['id']}/admins")
    assert initial.status_code == 200, initial.text
    assert initial.json() == [
        {
            "user_id": owner_id,
            "username": "fixture-event-admin",
            "display_name": "测试赛事管理员",
            "role": "OWNER",
            "active": True,
            "is_owner": True,
            "created_at": tournament["created_at"],
            "created_by_user_id": None,
        }
    ]

    granted = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": target["id"], "role": "OPERATOR"},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["role"] == "OPERATOR"
    assert granted.json()["is_owner"] is False
    assert granted.json()["created_by_user_id"] == owner_id

    updated = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": target["id"], "role": "VIEWER"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == "VIEWER"
    rows = conn.execute(
        "SELECT role, revoked_at, created_by_user_id FROM tournament_admins "
        "WHERE tournament_id = ? AND user_id = ?",
        (tournament["id"], target["id"]),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["role"] == "VIEWER"
    assert rows[0]["revoked_at"] is None
    assert rows[0]["created_by_user_id"] == owner_id

    revoked = client.delete(
        f"/api/tournaments/{tournament['id']}/admins/{target['id']}"
    )
    assert revoked.status_code == 204, revoked.text
    assert client.delete(
        f"/api/tournaments/{tournament['id']}/admins/{target['id']}"
    ).status_code == 204

    after_revoke = client.get(f"/api/tournaments/{tournament['id']}/admins")
    assert after_revoke.status_code == 200
    assert [item["user_id"] for item in after_revoke.json()] == [owner_id]
    persisted = conn.execute(
        "SELECT role, revoked_at FROM tournament_admins "
        "WHERE tournament_id = ? AND user_id = ?",
        (tournament["id"], target["id"]),
    ).fetchone()
    assert persisted["role"] == "VIEWER"
    assert persisted["revoked_at"] is not None

    restored = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": target["id"], "role": "ADMIN"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["role"] == "ADMIN"
    assert conn.execute(
        "SELECT COUNT(*) FROM tournament_admins WHERE tournament_id = ? AND user_id = ?",
        (tournament["id"], target["id"]),
    ).fetchone()[0] == 1


def test_admin_can_manage_and_non_managers_share_not_found(client, conn):
    tournament = _create_tournament(client)
    admin, admin_token = _create_user(conn, "d3a-admin")
    operator, operator_token = _create_user(conn, "d3a-operator")
    viewer, viewer_token = _create_user(conn, "d3a-viewer")
    outsider, outsider_token = _create_user(conn, "d3a-outsider")
    target, _ = _create_user(conn, "d3a-managed-target")

    _grant(conn, tournament["id"], admin["id"], TournamentRole.ADMIN)
    _grant(conn, tournament["id"], operator["id"], TournamentRole.OPERATOR)
    _grant(conn, tournament["id"], viewer["id"], TournamentRole.VIEWER)

    assert client.get(
        f"/api/tournaments/{tournament['id']}/admins",
        headers=_headers(admin_token),
    ).status_code == 200
    managed = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": target["id"], "role": "OPERATOR"},
        headers=_headers(admin_token),
    )
    assert managed.status_code == 200, managed.text
    assert managed.json()["created_by_user_id"] == admin["id"]

    denied_tokens = (operator_token, viewer_token, outsider_token)
    for token in denied_tokens:
        _assert_not_found(
            client.get(
                f"/api/tournaments/{tournament['id']}/admins",
                headers=_headers(token),
            )
        )
        _assert_not_found(
            client.post(
                f"/api/tournaments/{tournament['id']}/admins",
                json={"user_id": target["id"], "role": "VIEWER"},
                headers=_headers(token),
            )
        )
        _assert_not_found(
            client.delete(
                f"/api/tournaments/{tournament['id']}/admins/{target['id']}",
                headers=_headers(token),
            )
        )


def test_system_admin_has_no_implicit_tournament_access_or_manage_ability(client, conn):
    tournament = _create_tournament(client)
    system_admin, system_admin_token = _create_user(
        conn,
        "d3a-system-admin",
        system_role=SystemRole.SYSTEM_ADMIN,
    )

    _assert_not_found(
        client.get(
            f"/api/tournaments/{tournament['id']}/admins",
            headers=_headers(system_admin_token),
        )
    )
    rejected_target = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": system_admin["id"], "role": "OPERATOR"},
    )
    _assert_not_found(rejected_target)


def test_cross_tournament_owner_is_denied_with_not_found(client, conn):
    current = _create_tournament(client, "D3A 当前赛事")
    other_owner, other_token = _create_user(conn, "d3a-other-owner")
    other = _create_tournament(client, "D3A 另一赛事")
    conn.execute(
        "UPDATE tournaments SET owner_user_id = ? WHERE id = ?",
        (other_owner["id"], other["id"]),
    )
    conn.commit()

    headers = _headers(other_token)
    _assert_not_found(
        client.get(f"/api/tournaments/{current['id']}/admins", headers=headers)
    )
    _assert_not_found(
        client.post(
            f"/api/tournaments/{current['id']}/admins",
            json={"user_id": other_owner["id"], "role": "OPERATOR"},
            headers=headers,
        )
    )
    _assert_not_found(
        client.delete(
            f"/api/tournaments/{current['id']}/admins/{other_owner['id']}",
            headers=headers,
        )
    )


@pytest.mark.parametrize("role", ["OWNER", "SUPER_ADMIN", "", "X" * 33])
def test_grant_rejects_roles_outside_frozen_allowlist(client, conn, role):
    tournament = _create_tournament(client)
    target, _ = _create_user(conn, f"d3a-invalid-role-{role.lower()}")

    response = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": target["id"], "role": role},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == INVALID_TOURNAMENT_ROLE


def test_grant_rejects_unknown_inactive_and_system_admin_targets(client, conn):
    tournament = _create_tournament(client)
    inactive, _ = _create_user(conn, "d3a-inactive", active=False)
    system_admin, _ = _create_user(
        conn,
        "d3a-target-system-admin",
        system_role=SystemRole.SYSTEM_ADMIN,
    )

    for user_id in (99999999, inactive["id"], system_admin["id"]):
        response = client.post(
            f"/api/tournaments/{tournament['id']}/admins",
            json={"user_id": user_id, "role": "OPERATOR"},
        )
        _assert_not_found(response)


def test_owner_cannot_be_granted_or_revoked_through_regular_api(client):
    tournament = _create_tournament(client)
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    grant_owner = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": owner_id, "role": "OPERATOR"},
    )
    assert grant_owner.status_code == 409, grant_owner.text
    assert grant_owner.json()["detail"] == OWNER_PROTECTED

    revoke_owner = client.delete(
        f"/api/tournaments/{tournament['id']}/admins/{owner_id}"
    )
    assert revoke_owner.status_code == 409, revoke_owner.text
    assert revoke_owner.json()["detail"] == OWNER_PROTECTED


def test_role_change_and_revoke_immediately_affect_write_access(client, conn):
    tournament = _create_tournament(client, "D3A 即时权限赛事")
    target, target_token = _create_user(conn, "d3a-immediate-target")

    _grant(conn, tournament["id"], target["id"], TournamentRole.VIEWER)
    denied_as_viewer = client.post(
        f"/api/tournaments/{tournament['id']}/players",
        json={"name": "VIEWER 不应写入"},
        headers=_headers(target_token),
    )
    _assert_not_found(denied_as_viewer)

    _grant(conn, tournament["id"], target["id"], TournamentRole.OPERATOR)
    allowed_as_operator = client.post(
        f"/api/tournaments/{tournament['id']}/players",
        json={"name": "OPERATOR 写入成功"},
        headers=_headers(target_token),
    )
    assert allowed_as_operator.status_code == 201, allowed_as_operator.text

    _grant(conn, tournament["id"], target["id"], TournamentRole.VIEWER)
    denied_after_downgrade = client.post(
        f"/api/tournaments/{tournament['id']}/players",
        json={"name": "降级后不应写入"},
        headers=_headers(target_token),
    )
    _assert_not_found(denied_after_downgrade)

    _grant(conn, tournament["id"], target["id"], TournamentRole.OPERATOR)
    assert client.post(
        f"/api/tournaments/{tournament['id']}/players",
        json={"name": "重新升级后写入成功"},
        headers=_headers(target_token),
    ).status_code == 201

    assert client.delete(
        f"/api/tournaments/{tournament['id']}/admins/{target['id']}"
    ).status_code == 204
    denied_after_revoke = client.post(
        f"/api/tournaments/{tournament['id']}/players",
        json={"name": "撤销后不应写入"},
        headers=_headers(target_token),
    )
    _assert_not_found(denied_after_revoke)


def test_forfeit_reuses_existing_score_endpoint_with_tournament_permission(client, conn):
    tournament = _create_tournament(client, "D3A 异常结果权限赛事")
    for name in ("A 选手", "B 选手"):
        response = client.post(
            f"/api/tournaments/{tournament['id']}/players",
            json={"name": name},
        )
        assert response.status_code == 201, response.text
    assert client.post(
        f"/api/tournaments/{tournament['id']}/auto-group"
    ).status_code == 200
    assert client.post(
        f"/api/tournaments/{tournament['id']}/generate-group-matches"
    ).status_code == 200
    match = client.get(f"/api/tournaments/{tournament['id']}/matches").json()[0]

    outsider, outsider_token = _create_user(conn, "d3a-forfeit-outsider")
    operator, operator_token = _create_user(conn, "d3a-forfeit-operator")
    payload = {
        "result_type": "FORFEIT",
        "forfeit_entry_id": match["player_a_id"],
        "note": "A 方弃权",
    }

    denied = client.post(
        f"/api/matches/{match['id']}/score",
        json=payload,
        headers=_headers(outsider_token),
    )
    _assert_not_found(denied)

    granted = client.post(
        f"/api/tournaments/{tournament['id']}/admins",
        json={"user_id": operator["id"], "role": "OPERATOR"},
    )
    assert granted.status_code == 200, granted.text
    accepted = client.post(
        f"/api/matches/{match['id']}/score",
        json=payload,
        headers=_headers(operator_token),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["result_type"] == "FORFEIT"
    assert accepted.json()["forfeit_entry_id"] == match["player_a_id"]
    assert accepted.json()["winner_id"] == match["player_b_id"]
    assert outsider["id"] != operator["id"]

    client.headers.pop("Authorization")
    unauthenticated = client.post(f"/api/matches/{match['id']}/score", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert unauthenticated.json()["detail"]["code"] == "AUTH_REQUIRED"
