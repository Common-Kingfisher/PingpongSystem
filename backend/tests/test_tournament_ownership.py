"""A2.5：赛事归属与创建事务原子性。"""

from __future__ import annotations

from datetime import date

import pytest

from app import repository as repo
from app.services import tournaments as tournament_service


TOURNAMENT_PAYLOAD = {
    "name": "自有赛事",
    "date": "2026-09-21",
    "table_count": 1,
    "group_count": 1,
    "qualify_per_group": 1,
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_tournament(client, name: str, headers: dict[str, str] | None = None) -> dict:
    payload = {**TOURNAMENT_PAYLOAD, "name": name}
    response = client.post("/api/tournaments", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _create_second_event_admin_token() -> str:
    from app import db as db_module
    from app.models import SystemRole
    from app.security import hash_password
    from app.services import auth as auth_service

    username = "second-owner"
    password = "StrongPassword123"
    conn = db_module.connect()
    try:
        repo.create_user(
            conn,
            username,
            "第二管理员",
            hash_password(password, iterations=1000),
            SystemRole.EVENT_ADMIN.value,
        )
        conn.commit()
        return auth_service.login(conn, username, password)["access_token"]
    finally:
        conn.close()


def test_tournament_list_only_returns_owned_or_granted_and_hides_legacy(
    client, conn
):
    first = _create_tournament(client, "第一赛事")
    second_token = _create_second_event_admin_token()
    second = _create_tournament(client, "第二赛事", _headers(second_token))

    legacy = repo.create_tournament(
        conn,
        "历史无 Owner 赛事",
        "2026-09-20",
        1,
        1,
        1,
    )
    conn.commit()

    first_list = client.get("/api/tournaments").json()
    second_list = client.get("/api/tournaments", headers=_headers(second_token)).json()

    assert [item["id"] for item in first_list] == [first["id"]]
    assert [item["id"] for item in second_list] == [second["id"]]
    assert legacy["owner_user_id"] is None


def test_create_tournament_rolls_back_everything_when_table_creation_fails(
    conn, monkeypatch
):
    user = repo.create_user(
        conn,
        "rollback-owner",
        "回滚测试管理员",
        "test-hash",
        "EVENT_ADMIN",
    )
    conn.commit()

    def fail_table_creation(*_args, **_kwargs):
        raise RuntimeError("模拟球台创建失败")

    monkeypatch.setattr(repo, "create_tables_for_tournament", fail_table_creation)

    with pytest.raises(RuntimeError, match="模拟球台创建失败"):
        tournament_service.create_tournament_with_tables(
            conn,
            "应回滚赛事",
            date(2026, 9, 21),
            2,
            1,
            1,
            owner_user_id=user["id"],
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM tournaments WHERE name = ?", ("应回滚赛事",)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM tournament_admins WHERE user_id = ?", (user["id"],)
    ).fetchone()[0] == 0
