"""D2 A2.4：统一鉴权依赖与赛事级资源授权。"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import db as db_module
from app import repository as repo
from app.dependencies import (
    AuthContext,
    get_current_user,
    require_event_admin,
    require_system_admin,
    require_tournament_read,
    require_tournament_write,
)
from app.models import SystemRole, TournamentRole
from app.security import hash_password, hash_session_token
from app.services import auth as auth_service


PASSWORD = "StrongPassword123"
RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """使用独立临时数据库和最小测试 Router 验证依赖行为。"""
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "auth-dependencies.db"))
    monkeypatch.setenv("AUTH_PBKDF2_ITERATIONS", "1000")
    db_module.init_db()

    test_app = FastAPI()

    @test_app.get("/test/current-user")
    def current_user(context: AuthContext = Depends(get_current_user)):
        return {"user_id": context.user["id"]}

    @test_app.get("/test/cached-user")
    def cached_user(
        context: AuthContext = Depends(get_current_user),
        event_context: AuthContext = Depends(require_event_admin),
    ):
        return {
            "same_context": context is event_context,
            "user_id": context.user["id"],
        }

    @test_app.get("/test/system-admin")
    def system_admin(_: AuthContext = Depends(require_system_admin)):
        return {"allowed": True}

    @test_app.get("/test/event-admin")
    def event_admin(_: AuthContext = Depends(require_event_admin)):
        return {"allowed": True}

    @test_app.get("/test/tournaments/{tournament_id}/read")
    def read_tournament(
        access: dict = Depends(require_tournament_read),
    ):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.post("/test/tournaments/{tournament_id}/write")
    def write_tournament(
        access: dict = Depends(require_tournament_write),
    ):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/matches/{match_id}/read")
    def read_match(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/ties/{tie_id}/read")
    def read_tie(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/rubbers/{rubber_id}/read")
    def read_rubber(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/groups/{group_id}/read")
    def read_group(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/entries/{entry_id}/read")
    def read_entry(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/players/{player_id}/read")
    def read_player(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    @test_app.get("/test/tables/{table_id}/read")
    def read_table(access: dict = Depends(require_tournament_read)):
        return {"tournament_id": access["tournament_id"], "role": access["role"]}

    with TestClient(test_app) as client:
        yield client


def _create_user_and_token(
    username: str,
    system_role: SystemRole = SystemRole.EVENT_ADMIN,
) -> tuple[dict, str]:
    conn = db_module.connect()
    try:
        user = repo.create_user(
            conn,
            username,
            "测试用户",
            hash_password(PASSWORD, iterations=1000),
            system_role.value,
        )
        conn.commit()
        session = auth_service.login(conn, username, PASSWORD)
        return user, session["access_token"]
    finally:
        conn.close()


def _create_tournament(owner_user_id: int | None = None) -> dict:
    conn = db_module.connect()
    try:
        tournament = repo.create_tournament(
            conn,
            "依赖测试赛事",
            "2026-09-21",
            1,
            1,
            1,
        )
        if owner_user_id is not None:
            conn.execute(
                "UPDATE tournaments SET owner_user_id = ? WHERE id = ?",
                (owner_user_id, tournament["id"]),
            )
        conn.commit()
        return tournament
    finally:
        conn.close()


def _grant_tournament_role(tournament_id: int, user_id: int, role: TournamentRole) -> None:
    conn = db_module.connect()
    try:
        conn.execute(
            "INSERT INTO tournament_admins (tournament_id, user_id, role) VALUES (?, ?, ?)",
            (tournament_id, user_id, role.value),
        )
        conn.commit()
    finally:
        conn.close()


def _set_session_expired(token: str) -> None:
    conn = db_module.connect()
    try:
        conn.execute(
            "UPDATE user_sessions SET expires_at = ? WHERE token_hash = ?",
            ("2000-01-01T00:00:00+00:00", hash_session_token(token)),
        )
        conn.commit()
    finally:
        conn.close()


def _revoke_session(token: str) -> None:
    conn = db_module.connect()
    try:
        repo.revoke_user_session_by_hash(conn, hash_session_token(token))
        conn.commit()
    finally:
        conn.close()


def _deactivate_user(user_id: int) -> None:
    conn = db_module.connect()
    try:
        repo.set_user_active(conn, user_id, False)
        conn.commit()
    finally:
        conn.close()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_not_found(response) -> None:
    assert response.status_code == 404
    assert response.json()["detail"] == RESOURCE_NOT_FOUND


def test_current_user_rejects_missing_expired_and_revoked_sessions(api):
    missing = api.get("/test/current-user")
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "AUTH_REQUIRED"

    expired_user, expired_token = _create_user_and_token("expired-user")
    assert expired_user["id"] > 0
    _set_session_expired(expired_token)
    expired = api.get("/test/current-user", headers=_headers(expired_token))
    assert expired.status_code == 401
    assert expired.json()["detail"]["code"] == "AUTH_REQUIRED"

    revoked_user, revoked_token = _create_user_and_token("revoked-user")
    assert revoked_user["id"] > 0
    _revoke_session(revoked_token)
    revoked = api.get("/test/current-user", headers=_headers(revoked_token))
    assert revoked.status_code == 401
    assert revoked.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_inactive_user_is_rejected_with_bearer_and_cookie_sessions(api):
    user, token = _create_user_and_token("inactive-user")
    _deactivate_user(user["id"])

    conn = db_module.connect()
    try:
        session = conn.execute(
            "SELECT id, revoked_at FROM user_sessions WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert session is not None
    assert session["revoked_at"] is None

    bearer = api.get("/test/current-user", headers=_headers(token))
    assert bearer.status_code == 401
    assert bearer.json()["detail"]["code"] == "AUTH_REQUIRED"

    browser = api.get("/test/current-user", cookies={"pp_session": token})
    assert browser.status_code == 401
    assert browser.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_system_admin_passes_system_dependency_but_not_tournament_write(api):
    _, token = _create_user_and_token("system-admin", SystemRole.SYSTEM_ADMIN)
    tournament = _create_tournament()

    assert api.get("/test/system-admin", headers=_headers(token)).status_code == 200
    assert api.get("/test/event-admin", headers=_headers(token)).status_code == 403

    denied = api.post(
        f"/test/tournaments/{tournament['id']}/write",
        headers=_headers(token),
    )
    _assert_not_found(denied)


def test_event_admin_owner_can_read_and_write_owned_tournament(api):
    user, token = _create_user_and_token("owner")
    tournament = _create_tournament(user["id"])

    read = api.get(
        f"/test/tournaments/{tournament['id']}/read",
        headers=_headers(token),
    )
    write = api.post(
        f"/test/tournaments/{tournament['id']}/write",
        headers=_headers(token),
    )

    assert read.status_code == 200
    assert read.json()["role"] == TournamentRole.OWNER.value
    assert write.status_code == 200
    assert write.json()["role"] == TournamentRole.OWNER.value


def test_second_event_admin_gets_same_404_as_missing_tournament(api):
    owner, owner_token = _create_user_and_token("owner")
    other, other_token = _create_user_and_token("other-admin")
    tournament = _create_tournament(owner["id"])

    denied = api.get(
        f"/test/tournaments/{tournament['id']}/read",
        headers=_headers(other_token),
    )
    missing = api.get(
        "/test/tournaments/999999/read",
        headers=_headers(other_token),
    )
    owner_access = api.get(
        f"/test/tournaments/{tournament['id']}/read",
        headers=_headers(owner_token),
    )

    assert denied.status_code == 404
    assert missing.status_code == 404
    assert denied.json()["detail"] == missing.json()["detail"] == RESOURCE_NOT_FOUND
    assert owner_access.status_code == 200


def test_viewer_can_read_but_cannot_write(api):
    viewer, token = _create_user_and_token("viewer")
    tournament = _create_tournament()
    _grant_tournament_role(tournament["id"], viewer["id"], TournamentRole.VIEWER)

    read = api.get(
        f"/test/tournaments/{tournament['id']}/read",
        headers=_headers(token),
    )
    write = api.post(
        f"/test/tournaments/{tournament['id']}/write",
        headers=_headers(token),
    )

    assert read.status_code == 200
    assert read.json()["role"] == TournamentRole.VIEWER.value
    _assert_not_found(write)


def test_resource_ids_resolve_to_parent_tournament(api):
    user, token = _create_user_and_token("resource-owner")
    tournament = _create_tournament(user["id"])

    conn = db_module.connect()
    try:
        group = repo.create_group(conn, tournament["id"], "A组", 1)
        entry_a = repo.create_entry(
            conn, tournament["id"], "SINGLES", "选手A", 1000, []
        )
        entry_b = repo.create_entry(
            conn, tournament["id"], "SINGLES", "选手B", 1000, []
        )
        player = repo.add_player(conn, tournament["id"], "选手A", "测试学院")
        table = repo.create_tables_for_tournament(conn, tournament["id"], 1)[0]
        match = repo.create_match(
            conn,
            tournament["id"],
            "GROUP",
            group["id"],
            1,
            1,
            None,
            None,
            entry_a_id=entry_a["id"],
            entry_b_id=entry_b["id"],
        )
        tie = repo.create_team_tie(
            conn,
            tournament["id"],
            "GROUP",
            group["id"],
            1,
            1,
            entry_a["id"],
            entry_b["id"],
        )
        rubber = repo.create_team_rubber(
            conn, tie["id"], 1, "SINGLES", "[]", "[]"
        )
        conn.commit()
    finally:
        conn.close()

    paths = (
        f"/test/matches/{match['id']}/read",
        f"/test/ties/{tie['id']}/read",
        f"/test/rubbers/{rubber['id']}/read",
        f"/test/groups/{group['id']}/read",
        f"/test/entries/{entry_a['id']}/read",
        f"/test/players/{player['id']}/read",
        f"/test/tables/{table['id']}/read",
    )
    for path in paths:
        response = api.get(path, headers=_headers(token))
        assert response.status_code == 200, path
        assert response.json()["tournament_id"] == tournament["id"], path

    invalid = api.get("/test/matches/not-an-id/read", headers=_headers(token))
    missing = api.get("/test/matches/999999/read", headers=_headers(token))
    _assert_not_found(invalid)
    _assert_not_found(missing)


def test_authentication_dependency_is_cached_within_one_request(api, monkeypatch):
    _, token = _create_user_and_token("cached-user")
    calls = {"count": 0}
    original = auth_service.authenticate_session

    def counting_authenticate_session(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        auth_service, "authenticate_session", counting_authenticate_session
    )

    response = api.get("/test/cached-user", headers=_headers(token))

    assert response.status_code == 200
    assert response.json()["same_context"] is True
    assert calls["count"] == 1
