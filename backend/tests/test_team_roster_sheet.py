"""团体赛 Excel 名单工作表：原子保存、冻结与撤销冻结。"""

import pytest

from app import repository as repo
from app.models import EventType
from app.services import team_roster, teams


def _team_tournament(client):
    return client.post("/api/tournaments", json={
        "name": "名单工作表", "date": "2026-09-19", "table_count": 2,
        "group_count": 1, "qualify_per_group": 1, "event_type": "TEAM",
    }).json()["id"]


def _sheet_payload(sheet):
    teams = [{
        "key": f"team-{team['id']}", "id": team["id"],
        "display_name": team["display_name"], "rating_points": team["rating_points"],
        "sort_order": team["sort_order"],
    } for team in sheet["teams"]]
    team_of = {
        member["player_id"]: f"team-{team['id']}"
        for team in sheet["teams"] for member in team["members"]
    }
    order_of = {
        member["player_id"]: member["member_order"]
        for team in sheet["teams"] for member in team["members"]
    }
    players = [{
        "key": f"player-{player['id']}", "id": player["id"], "name": player["name"],
        "college": player["college"], "rating_points": player["rating_points"],
        "team_key": team_of.get(player["id"]), "member_order": order_of.get(player["id"]),
    } for player in sheet["players"]]
    return {"base_revision": sheet["revision"], "teams": teams, "players": players,
            "deleted_team_ids": [], "deleted_player_ids": []}


def _seed(client):
    tid = _team_tournament(client)
    players = [client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json() for i in range(1, 5)]
    client.post(f"/api/tournaments/{tid}/teams", json={"display_name": "甲队", "member_ids": [players[0]["id"], players[1]["id"]]})
    client.post(f"/api/tournaments/{tid}/teams", json={"display_name": "乙队", "member_ids": [players[2]["id"], players[3]["id"]]})
    return tid


def test_sheet_save_moves_member_and_preserves_explicit_order(client):
    tid = _seed(client)
    sheet = client.get(f"/api/tournaments/{tid}/team-roster").json()
    payload = _sheet_payload(sheet)
    first, second = payload["teams"]
    moved = payload["players"][1]
    moved["team_key"] = second["key"]
    moved["member_order"] = 3
    payload["players"][2]["member_order"] = 1
    payload["players"][3]["member_order"] = 2
    payload["teams"] = [second, first]
    payload["teams"][0]["sort_order"] = 1
    payload["teams"][1]["sort_order"] = 2

    saved = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert [team["display_name"] for team in body["teams"]] == ["乙队", "甲队"]
    assert [member["name"] for member in body["teams"][0]["members"]] == ["P3", "P4", "P2"]


def test_sheet_rejects_stale_revision_without_overwrite(client):
    tid = _seed(client)
    sheet = client.get(f"/api/tournaments/{tid}/team-roster").json()
    payload = _sheet_payload(sheet)
    client.patch(f"/api/tournaments/{tid}/teams/{sheet['teams'][0]['id']}", json={"display_name": "已更新"})
    response = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert response.status_code == 409
    assert "刷新" in response.json()["detail"]


def test_confirmation_freezes_writes_until_unconfirmed(client):
    tid = _seed(client)
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    sheet = client.get(f"/api/tournaments/{tid}/team-roster").json()
    assert sheet["tournament"]["roster_confirmed"] is True
    blocked = client.post(f"/api/tournaments/{tid}/players", json={"name": "冻结后新增"})
    assert blocked.status_code == 409
    blocked_seed = client.put(f"/api/tournaments/{tid}/seeds", json={"player_ids": []})
    assert blocked_seed.status_code == 409
    restored = client.post(f"/api/tournaments/{tid}/team-roster/unconfirm")
    assert restored.status_code == 200
    assert restored.json()["tournament"]["roster_confirmed"] is False
    assert client.post(f"/api/tournaments/{tid}/players", json={"name": "恢复后新增"}).status_code == 201


def test_sheet_cannot_change_members_of_team_with_started_tie(conn):
    tournament = repo.create_tournament(
        conn, "开赛名单保护", "2026-09-19", 2, 1, 1, event_type=EventType.TEAM.value
    )
    tid = tournament["id"]
    players = [repo.add_player(conn, tid, f"P{i}", None) for i in range(1, 5)]
    first = teams.create_team_entry(conn, tid, "甲队", [players[0]["id"], players[1]["id"]])
    second = teams.create_team_entry(conn, tid, "乙队", [players[2]["id"], players[3]["id"]])
    tie = repo.create_team_tie(conn, tid, "GROUP", None, 1, 1, first["id"], second["id"])
    conn.execute("UPDATE team_ties SET status = 'PLAYING' WHERE id = ?", (tie["id"],))
    conn.commit()

    payload = _sheet_payload(team_roster.get_sheet(conn, tid))
    payload["players"][0]["team_key"] = payload["teams"][1]["key"]
    payload["players"][0]["member_order"] = 3
    payload["players"][1]["member_order"] = 1

    with pytest.raises(teams.TeamError, match="不能修改队员") as error:
        team_roster.save_sheet(conn, tid, payload)
    assert error.value.code == 409
