"""D5A：报名开关、公开提交与管理端读取 API。"""

from __future__ import annotations

from app import repository as repo
from app.models import EventType, SystemRole, TournamentStage
from app.security import hash_password
from app.services import auth as auth_service


PASSWORD = "StrongPassword123"
TOURNAMENT_PAYLOAD = {
    "name": "D5A 报名 API 赛事",
    "date": "2026-09-22",
    "table_count": 2,
    "group_count": 2,
    "qualify_per_group": 1,
}
REGISTRATION_PAYLOAD = {
    "name": "公开报名选手",
    "affiliation": "计算机学院",
    "contact": "13800000000",
    "rating_points": 1680,
}
RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}


def _create_tournament(
    client,
    name: str = TOURNAMENT_PAYLOAD["name"],
    *,
    registration_enabled: bool = False,
    event_type: str = EventType.SINGLES.value,
) -> dict:
    response = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "name": name,
            "registration_enabled": registration_enabled,
            "event_type": event_type,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_event_admin(conn, username: str) -> tuple[dict, str]:
    user = repo.create_user(
        conn,
        username,
        f"{username} 显示名",
        hash_password(PASSWORD, iterations=1000),
        SystemRole.EVENT_ADMIN.value,
    )
    conn.commit()
    token = auth_service.login(conn, username, PASSWORD)["access_token"]
    return user, token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registration_enabled_round_trip_and_persisted(client, conn):
    default_tournament = _create_tournament(client, "默认关闭报名")
    assert default_tournament["registration_enabled"] is False
    assert repo.get_tournament(conn, default_tournament["id"])[
        "registration_enabled"
    ] == 0

    enabled_tournament = _create_tournament(
        client, "创建时开启报名", registration_enabled=True
    )
    assert enabled_tournament["registration_enabled"] is True
    assert repo.get_tournament(conn, enabled_tournament["id"])[
        "registration_enabled"
    ] == 1

    disabled = client.put(
        f"/api/tournaments/{enabled_tournament['id']}/registration",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["registration_enabled"] is False
    assert repo.get_tournament(conn, enabled_tournament["id"])[
        "registration_enabled"
    ] == 0


def test_registration_cannot_reopen_after_roster_confirmation_or_stage_change(client, conn):
    confirmed = _create_tournament(client, "已确认名单禁止开启报名")
    conn.execute(
        "UPDATE tournaments SET roster_confirmed = 1 WHERE id = ?", (confirmed["id"],)
    )
    conn.commit()
    locked = client.put(
        f"/api/tournaments/{confirmed['id']}/registration", json={"enabled": True}
    )
    assert locked.status_code == 409, locked.text
    assert locked.json()["detail"] == {
        "code": "REGISTRATION_CLOSED",
        "message": "参赛名单已确认，报名已关闭",
    }

    started = _create_tournament(client, "已开赛禁止开启报名")
    repo.update_tournament_stage(conn, started["id"], TournamentStage.GROUP_STAGE.value)
    conn.commit()
    staged = client.put(
        f"/api/tournaments/{started['id']}/registration", json={"enabled": True}
    )
    assert staged.status_code == 409, staged.text
    assert staged.json()["detail"] == {
        "code": "REGISTRATION_CLOSED",
        "message": "赛事已开赛，报名已关闭",
    }


def test_registration_can_clear_stale_enabled_flag_after_roster_confirmation(client, conn):
    tournament = _create_tournament(
        client, "清理历史报名开关", registration_enabled=True
    )
    conn.execute(
        "UPDATE tournaments SET roster_confirmed = 1 WHERE id = ?", (tournament["id"],)
    )
    conn.commit()

    response = client.put(
        f"/api/tournaments/{tournament['id']}/registration", json={"enabled": False}
    )
    assert response.status_code == 200, response.text
    assert response.json()["registration_enabled"] is False


def test_team_registration_toggle_cannot_enable_but_can_clear_stale_flag(client, conn):
    team = _create_tournament(
        client,
        "团体赛报名开关守卫",
        event_type=EventType.TEAM.value,
    )
    enabled = client.put(
        f"/api/tournaments/{team['id']}/registration", json={"enabled": True}
    )
    assert enabled.status_code == 409, enabled.text
    assert enabled.json()["detail"] == {
        "code": "UNSUPPORTED_REGISTRATION_EVENT_TYPE",
        "message": "团体赛暂不支持公开个人报名",
    }
    assert repo.get_tournament(conn, team["id"])["registration_enabled"] == 0

    conn.execute(
        "UPDATE tournaments SET registration_enabled = 1 WHERE id = ?", (team["id"],)
    )
    conn.commit()
    disabled = client.put(
        f"/api/tournaments/{team['id']}/registration", json={"enabled": False}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["registration_enabled"] is False
    assert repo.get_tournament(conn, team["id"])["registration_enabled"] == 0


def _side_effect_counts(conn) -> tuple[int, int, int]:
    """赛事创建的所有落库副作用的行数快照：Tournament / Tables / Owner 授权。"""
    return (
        conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM tables").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM tournament_admins").fetchone()[0],
    )


def test_team_tournament_cannot_be_created_with_public_registration_enabled(client, conn):
    """TEAM + registration_enabled=true 必须在赛事创建 service 边界被明确拒绝。

    否则 `POST /api/tournaments` 会写入 `registration_enabled=1`，而
    `POST /api/tournaments/{tid}/registrations` 对 TEAM 固定返回
    `UNSUPPORTED_REGISTRATION_EVENT_TYPE`，形成「flag 显示已开启、实际永远提交不进去」的双状态。
    """
    before = _side_effect_counts(conn)

    response = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "name": "团体赛创建时开启公开报名",
            "event_type": EventType.TEAM.value,
            "registration_enabled": True,
        },
    )

    assert response.status_code == 409, response.text
    # 遵循当前 TournamentFormatError 的 router mapping：纯文本 detail，不新增结构化 DTO
    assert response.json()["detail"] == "团体赛暂不支持公开个人报名"

    # 失败必须发生在任何数据库副作用之前：Tournament / Tables / Owner 授权都不得残留
    assert _side_effect_counts(conn) == before
    assert conn.execute(
        "SELECT COUNT(*) FROM tournaments WHERE name = ?",
        ("团体赛创建时开启公开报名",),
    ).fetchone()[0] == 0


def test_team_tournament_creation_without_registration_flag_is_unaffected(client):
    """守卫只针对 TEAM + true：缺省 / false 的团体赛创建不得被误伤。"""
    created = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "name": "团体赛正常创建",
            "event_type": EventType.TEAM.value,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["registration_enabled"] is False


def test_doubles_tournament_can_still_be_created_with_registration_enabled(client):
    """守卫只针对 TEAM：双打（与单打）创建时开启公开报名仍然合法。"""
    created = client.post(
        "/api/tournaments",
        json={
            **TOURNAMENT_PAYLOAD,
            "name": "双打开启报名",
            "event_type": EventType.DOUBLES.value,
            "registration_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["registration_enabled"] is True


def test_public_submit_only_creates_pending_and_hides_contact(client, conn):
    enabled = _create_tournament(
        client, "公开报名隐私赛事", registration_enabled=True
    )
    disabled = _create_tournament(client, "关闭报名赛事")
    client.headers.pop("Authorization")

    response = client.post(
        f"/api/tournaments/{enabled['id']}/registrations",
        json=REGISTRATION_PAYLOAD,
    )
    assert response.status_code == 201, response.text
    assert set(response.json()) == {
        "registration_id",
        "status",
        "name",
        "created_at",
    }
    assert response.json()["status"] == "PENDING"
    assert "contact" not in response.text
    assert "affiliation" not in response.text
    assert "rating_points" not in response.text

    persisted = repo.get_registration(conn, response.json()["registration_id"])
    assert persisted["tournament_id"] == enabled["id"]
    assert persisted["contact"] == REGISTRATION_PAYLOAD["contact"]
    assert persisted["affiliation"] == REGISTRATION_PAYLOAD["affiliation"]
    assert repo.list_players(conn, enabled["id"]) == []
    assert conn.execute(
        "SELECT COUNT(*) FROM entries WHERE tournament_id = ?", (enabled["id"],)
    ).fetchone()[0] == 0

    closed = client.post(
        f"/api/tournaments/{disabled['id']}/registrations",
        json=REGISTRATION_PAYLOAD,
    )
    assert closed.status_code == 409, closed.text
    assert closed.json()["detail"]["code"] == "REGISTRATION_CLOSED"

    missing = client.post(
        "/api/tournaments/999999/registrations", json=REGISTRATION_PAYLOAD
    )
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"] == RESOURCE_NOT_FOUND


def test_registration_closed_after_stage_and_for_team_event(client, conn):
    singles = _create_tournament(
        client, "已开赛报名赛事", registration_enabled=True
    )
    repo.update_tournament_stage(conn, singles["id"], TournamentStage.GROUP_STAGE.value)
    conn.commit()

    closed = client.post(
        f"/api/tournaments/{singles['id']}/registrations",
        json=REGISTRATION_PAYLOAD,
    )
    assert closed.status_code == 409, closed.text
    assert closed.json()["detail"] == {
        "code": "REGISTRATION_CLOSED",
        "message": "赛事已开赛，报名已关闭",
    }

    team = _create_tournament(
        client,
        "团体赛公开报名拒绝",
        event_type=EventType.TEAM.value,
    )
    unsupported = client.post(
        f"/api/tournaments/{team['id']}/registrations",
        json=REGISTRATION_PAYLOAD,
    )
    assert unsupported.status_code == 409, unsupported.text
    assert unsupported.json()["detail"]["code"] == (
        "UNSUPPORTED_REGISTRATION_EVENT_TYPE"
    )


def test_admin_registration_list_is_scoped_filterable_and_login_required(
    client, conn
):
    first = _create_tournament(
        client, "报名列表赛事 A", registration_enabled=True
    )
    second = _create_tournament(
        client, "报名列表赛事 B", registration_enabled=True
    )
    first_one = client.post(
        f"/api/tournaments/{first['id']}/registrations",
        json={**REGISTRATION_PAYLOAD, "name": "A1"},
    ).json()
    client.post(
        f"/api/tournaments/{first['id']}/registrations",
        json={**REGISTRATION_PAYLOAD, "name": "A2"},
    )
    client.post(
        f"/api/tournaments/{second['id']}/registrations",
        json={**REGISTRATION_PAYLOAD, "name": "B1"},
    )

    listed = client.get(f"/api/tournaments/{first['id']}/registrations")
    assert listed.status_code == 200, listed.text
    assert [item["name"] for item in listed.json()] == ["A1", "A2"]
    assert listed.json()[0]["contact"] == REGISTRATION_PAYLOAD["contact"]

    pending = client.get(
        f"/api/tournaments/{first['id']}/registrations",
        params={"status": "PENDING"},
    )
    assert pending.status_code == 200, pending.text
    assert len(pending.json()) == 2
    assert client.get(
        f"/api/tournaments/{first['id']}/registrations",
        params={"status": "CONFIRMED"},
    ).json() == []

    confirmed = client.post(
        f"/api/tournaments/{first['id']}/registrations/"
        f"{first_one['registration_id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert len(
        client.get(
            f"/api/tournaments/{first['id']}/registrations",
            params={"status": "CONFIRMED"},
        ).json()
    ) == 1

    _, other_token = _create_event_admin(conn, "d5a-registration-outsider")
    outsider = client.get(
        f"/api/tournaments/{first['id']}/registrations",
        headers=_headers(other_token),
    )
    assert outsider.status_code == 404, outsider.text
    assert outsider.json()["detail"] == RESOURCE_NOT_FOUND

    client.headers.pop("Authorization")
    anonymous = client.get(f"/api/tournaments/{first['id']}/registrations")
    assert anonymous.status_code == 401, anonymous.text
    assert anonymous.json()["detail"]["code"] == "AUTH_REQUIRED"
