"""团体赛 Excel 名单工作表：原子保存、校验、冻结与并发保护。"""

import threading

import pytest

from app import db as db_module
from app import repository as repo
from app.models import EventType
from app.services import players, team_roster, teams


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


def _seed_conn(conn):
    tournament = repo.create_tournament(
        conn, "工作表服务", "2026-09-19", 2, 1, 1, event_type=EventType.TEAM.value
    )
    tid = tournament["id"]
    players = [repo.add_player(conn, tid, f"P{i}", None) for i in range(1, 5)]
    conn.commit()
    teams.create_team_entry(conn, tid, "甲队", [players[0]["id"], players[1]["id"]])
    teams.create_team_entry(conn, tid, "乙队", [players[2]["id"], players[3]["id"]])
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


def test_sheet_creates_team_and_player_in_one_atomic_save(client):
    tid = _seed(client)
    payload = _sheet_payload(client.get(f"/api/tournaments/{tid}/team-roster").json())
    payload["teams"].append({
        "key": "team-new", "id": None, "display_name": "丙队", "rating_points": 1250, "sort_order": 3,
    })
    payload["players"].append({
        "key": "player-new", "id": None, "name": "新队员", "college": "测试学院",
        "rating_points": 1300, "team_key": "team-new", "member_order": 1,
    })

    response = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert response.status_code == 200, response.text
    created = response.json()
    assert [team["display_name"] for team in created["teams"]] == ["甲队", "乙队", "丙队"]
    assert created["teams"][2]["members"][0]["name"] == "新队员"


def test_sheet_explicit_deletes_keep_unassigned_players(client):
    tid = _seed(client)
    payload = _sheet_payload(client.get(f"/api/tournaments/{tid}/team-roster").json())
    removed_team = payload["teams"].pop()
    removed_player = payload["players"].pop()
    payload["deleted_team_ids"] = [removed_team["id"]]
    payload["deleted_player_ids"] = [removed_player["id"]]
    player_from_removed_team = payload["players"].pop()
    player_from_removed_team["team_key"] = None
    player_from_removed_team["member_order"] = None
    payload["players"].append(player_from_removed_team)

    response = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [team["display_name"] for team in body["teams"]] == ["甲队"]
    assert {player["name"] for player in body["players"]} == {"P1", "P2", "P3"}
    assert "P3" not in {member["name"] for member in body["teams"][0]["members"]}


def test_sheet_rejects_stale_revision_without_overwrite(client):
    tid = _seed(client)
    sheet = client.get(f"/api/tournaments/{tid}/team-roster").json()
    payload = _sheet_payload(sheet)
    client.patch(f"/api/tournaments/{tid}/teams/{sheet['teams'][0]['id']}", json={"display_name": "已更新"})
    response = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert response.status_code == 409
    assert "刷新" in response.json()["detail"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: [
                payload["players"][0].update({"team_key": payload["teams"][1]["key"], "member_order": 3}),
                payload["players"][1].update({"team_key": payload["teams"][1]["key"], "member_order": 4}),
                payload["players"][2].update({"member_order": 1}),
                payload["players"][3].update({"member_order": 2}),
            ],
            "至少需要 1 名队员",
        ),
        (lambda payload: payload["teams"][1].update({"display_name": payload["teams"][0]["display_name"]}), "队伍名称不能重复"),
        (lambda payload: payload["players"][1].update({"member_order": 3}), "必须从 1 连续排列"),
    ],
)
def test_sheet_rejects_invalid_drafts(client, mutate, message):
    tid = _seed(client)
    payload = _sheet_payload(client.get(f"/api/tournaments/{tid}/team-roster").json())
    mutate(payload)
    response = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_sheet_rejects_foreign_record_id(client):
    tid = _seed(client)
    payload = _sheet_payload(client.get(f"/api/tournaments/{tid}/team-roster").json())
    payload["players"][0]["id"] = 999_999
    response = client.put(f"/api/tournaments/{tid}/team-roster", json=payload)
    assert response.status_code == 404
    assert "不属于本赛事" in response.json()["detail"]


def test_confirmation_freezes_writes_until_unconfirmed(client):
    tid = _seed(client)
    assert client.post(f"/api/tournaments/{tid}/confirm-roster").status_code == 200
    sheet = client.get(f"/api/tournaments/{tid}/team-roster").json()
    assert sheet["tournament"]["roster_confirmed"] is True
    blocked = client.post(f"/api/tournaments/{tid}/players", json={"name": "冻结后新增"})
    assert blocked.status_code == 409
    team_id = client.get(f"/api/tournaments/{tid}/team-roster").json()["teams"][0]["id"]
    assert client.patch(f"/api/tournaments/{tid}/teams/{team_id}", json={"display_name": "冻结后改名"}).status_code == 409
    assert client.delete(f"/api/tournaments/{tid}/teams/{team_id}").status_code == 409
    imported = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("players.csv", "姓名,单位\n冻结导入,测试学院\n", "text/csv")},
    )
    assert imported.status_code == 409
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
    conn.commit()
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


def test_unconfirm_rejects_started_team_tie(conn):
    tid = _seed_conn(conn)
    entries = repo.list_entries_by_type(conn, tid, EventType.TEAM.value)
    tie = repo.create_team_tie(conn, tid, "GROUP", None, 1, 1, entries[0]["id"], entries[1]["id"])
    conn.execute("UPDATE tournaments SET roster_confirmed = 1 WHERE id = ?", (tid,))
    conn.execute("UPDATE team_ties SET status = 'PLAYING' WHERE id = ?", (tie["id"],))
    conn.commit()

    with pytest.raises(teams.TeamError, match="已有团体对抗开始或结束") as error:
        team_roster.unconfirm_roster(conn, tid)
    assert error.value.code == 409


def test_sheet_enforces_120_player_limit(conn):
    tournament = repo.create_tournament(
        conn, "名单人数上限", "2026-09-19", 2, 1, 1, event_type=EventType.TEAM.value
    )
    tid = tournament["id"]
    for index in range(120):
        repo.add_player(conn, tid, f"P{index}", None)
    conn.commit()
    payload = _sheet_payload(team_roster.get_sheet(conn, tid))
    payload["players"].append({
        "key": "player-over-limit", "id": None, "name": "超额选手", "college": None,
        "rating_points": 1000, "team_key": None, "member_order": None,
    })

    with pytest.raises(players.PlayerError, match="最多支持 120 名运动员") as error:
        team_roster.save_sheet(conn, tid, payload)
    assert error.value.code == 409


def test_two_concurrent_sheet_saves_only_one_commits(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "concurrent.db"))
    db_module.init_db()
    setup = db_module.connect()
    try:
        tid = _seed_conn(setup)
        sheet = team_roster.get_sheet(setup, tid)
        first = _sheet_payload(sheet)
        second = _sheet_payload(sheet)
        first["players"][0]["name"] = "并发保存甲"
        second["players"][0]["name"] = "并发保存乙"
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    outcomes = []
    outcome_lock = threading.Lock()

    def save(payload):
        worker = db_module.connect()
        try:
            barrier.wait(timeout=5)
            team_roster.save_sheet(worker, tid, payload)
            outcome = 200
        except teams.TeamError as exc:
            outcome = exc.code
        finally:
            worker.close()
        with outcome_lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=save, args=(payload,)) for payload in (first, second)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()

    assert sorted(outcomes) == [200, 409]
