"""D5A：赛事组织方与场馆最小 API、权限及数据边界。"""

from __future__ import annotations

from app import repository as repo
from app.models import SystemRole, TournamentRole
from app.security import hash_password
from app.services import auth as auth_service


PASSWORD = "StrongPassword123"
RESOURCE_NOT_FOUND = {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}
TOURNAMENT_PAYLOAD = {
    "name": "D5A 组织场馆赛事",
    "date": "2026-09-22",
    "table_count": 3,
    "group_count": 2,
    "qualify_per_group": 1,
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_user(
    conn,
    username: str,
    system_role: SystemRole = SystemRole.EVENT_ADMIN,
) -> tuple[dict, str]:
    user = repo.create_user(
        conn,
        username,
        f"{username} 显示名",
        hash_password(PASSWORD, iterations=1000),
        system_role.value,
    )
    conn.commit()
    token = auth_service.login(conn, username, PASSWORD)["access_token"]
    return user, token


def _grant(conn, tournament_id: int, user_id: int, role: TournamentRole) -> None:
    repo.upsert_tournament_admin(
        conn, tournament_id, user_id, role.value, created_by_user_id=1
    )
    conn.commit()


def _create_tournament(client, name: str = TOURNAMENT_PAYLOAD["name"]) -> dict:
    response = client.post(
        "/api/tournaments", json={**TOURNAMENT_PAYLOAD, "name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_organization_and_venue_upsert_without_replacing_tables(client):
    tournament = _create_tournament(client)
    tournament_id = tournament["id"]

    missing_org = client.get(f"/api/tournaments/{tournament_id}/organization")
    assert missing_org.status_code == 404, missing_org.text
    assert missing_org.json()["detail"]["code"] == "ORGANIZATION_NOT_FOUND"
    missing_venue = client.get(f"/api/tournaments/{tournament_id}/venue")
    assert missing_venue.status_code == 404, missing_venue.text
    assert missing_venue.json()["detail"]["code"] == "VENUE_NOT_FOUND"

    organization = client.put(
        f"/api/tournaments/{tournament_id}/organization",
        json={
            "name": "示例乒乓球协会",
            "contact_name": "组织联系人",
            "contact": "010-12345678",
            "note": "仅表示赛事组织方，不参与单位规避",
        },
    )
    assert organization.status_code == 200, organization.text
    assert organization.json()["tournament_id"] == tournament_id
    assert organization.json()["name"] == "示例乒乓球协会"

    venue = client.put(
        f"/api/tournaments/{tournament_id}/venue",
        json={
            "name": "示例体育馆",
            "address": "示例路 1 号",
            "contact_name": "场馆联系人",
            "contact": "020-87654321",
            "note": "场地信息不复制球台",
        },
    )
    assert venue.status_code == 200, venue.text
    assert venue.json()["tournament_id"] == tournament_id
    assert venue.json()["address"] == "示例路 1 号"

    # 通过公开赛事详情读取球台数量，确认组织方/场馆写入不会触碰 tables。
    tournament_after = client.get(f"/api/tournaments/{tournament_id}").json()
    assert tournament_after["table_count"] == tournament["table_count"]

    updated = client.put(
        f"/api/tournaments/{tournament_id}/organization",
        json={"name": "新的组织方名称"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == organization.json()["id"]
    assert updated.json()["contact"] is None
    assert client.get(
        f"/api/tournaments/{tournament_id}/organization"
    ).json()["name"] == "新的组织方名称"

    connection = None
    try:
        from app import db as db_module

        connection = db_module.connect()
        assert connection.execute(
            "SELECT COUNT(*) FROM tables WHERE tournament_id = ?",
            (tournament_id,),
        ).fetchone()[0] == tournament["table_count"]
        assert connection.execute(
            "SELECT COUNT(*) FROM organizations WHERE tournament_id = ?",
            (tournament_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM venues WHERE tournament_id = ?",
            (tournament_id,),
        ).fetchone()[0] == 1
    finally:
        if connection is not None:
            connection.close()


def test_organization_and_venue_permissions_and_public_privacy(client, conn):
    tournament = _create_tournament(client, "组织场馆权限赛事")
    client.put(
        f"/api/tournaments/{tournament['id']}/organization",
        json={"name": "受保护组织方", "contact": "010-00000000"},
    )
    client.put(
        f"/api/tournaments/{tournament['id']}/venue",
        json={"name": "受保护场馆", "contact": "020-00000000"},
    )

    viewer, viewer_token = _create_user(conn, "d5a-org-viewer")
    _grant(conn, tournament["id"], viewer["id"], TournamentRole.VIEWER)
    assert client.get(
        f"/api/tournaments/{tournament['id']}/organization",
        headers=_headers(viewer_token),
    ).status_code == 200
    viewer_write = client.put(
        f"/api/tournaments/{tournament['id']}/venue",
        json={"name": "只读用户不应写入"},
        headers=_headers(viewer_token),
    )
    assert viewer_write.status_code == 404, viewer_write.text
    assert viewer_write.json()["detail"] == RESOURCE_NOT_FOUND

    outsider, outsider_token = _create_user(conn, "d5a-org-outsider")
    outsider_read = client.get(
        f"/api/tournaments/{tournament['id']}/organization",
        headers=_headers(outsider_token),
    )
    assert outsider_read.status_code == 404, outsider_read.text
    assert outsider_read.json()["detail"] == RESOURCE_NOT_FOUND

    system_admin, system_admin_token = _create_user(
        conn, "d5a-system-admin", SystemRole.SYSTEM_ADMIN
    )
    admin_read = client.get(
        f"/api/tournaments/{tournament['id']}/venue",
        headers=_headers(system_admin_token),
    )
    assert admin_read.status_code == 404, admin_read.text
    assert admin_read.json()["detail"] == RESOURCE_NOT_FOUND

    client.headers.pop("Authorization")
    public_org = client.get(f"/api/tournaments/{tournament['id']}/organization")
    assert public_org.status_code == 401, public_org.text
    public_venue = client.get(f"/api/tournaments/{tournament['id']}/venue")
    assert public_venue.status_code == 401, public_venue.text
    public_tournament = client.get(f"/api/tournaments/{tournament['id']}")
    assert public_tournament.status_code == 200, public_tournament.text
    assert "受保护组织方" not in public_tournament.text
    assert "010-00000000" not in public_tournament.text
    assert "受保护场馆" not in public_tournament.text
    assert "020-00000000" not in public_tournament.text


def test_organization_and_venue_delete_with_tournament_cascade(client):
    tournament = _create_tournament(client, "组织场馆级联删除赛事")
    tournament_id = tournament["id"]
    client.put(
        f"/api/tournaments/{tournament_id}/organization",
        json={"name": "待级联组织方"},
    )
    client.put(
        f"/api/tournaments/{tournament_id}/venue",
        json={"name": "待级联场馆"},
    )
    enabled = client.put(
        f"/api/tournaments/{tournament_id}/registration",
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    registration = client.post(
        f"/api/tournaments/{tournament_id}/registrations",
        json={"name": "待级联报名"},
    )
    assert registration.status_code == 201, registration.text

    from app import db as db_module

    conn = db_module.connect()
    try:
        for table in ("organizations", "venues", "registrations"):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE tournament_id = ?",
                (tournament_id,),
            ).fetchone()[0] == 1
    finally:
        conn.close()

    deleted = client.delete(
        f"/api/tournaments/{tournament_id}",
        params={"confirm_name": tournament["name"]},
    )
    assert deleted.status_code == 204, deleted.text

    conn = db_module.connect()
    try:
        for table in ("organizations", "venues", "registrations"):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE tournament_id = ?",
                (tournament_id,),
            ).fetchone()[0] == 0
    finally:
        conn.close()
