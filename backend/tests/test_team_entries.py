"""A3：团体队伍（TeamEntry）—— 复用 entries/entry_members 的名单领域与业务守卫。

覆盖：TEAM 专属校验（项目类型、阶段锁定、队员唯一归属、重名）、名单确认三分支、
以及"二元假设"回归（TEAM 队伍不得被当成单打实体去播种/配对/生成比赛）。
"""

import pytest

from app import repository as repo
from app.models import EventType, TournamentStage
from app.services import entries as entry_service
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import players as players_service
from app.services import teams as teams_service


def _create_tournament(conn, *, event_type: str = "TEAM", players: int = 6, group_count: int = 2) -> int:
    tournament = repo.create_tournament(
        conn, "团体验收", "2026-05-01", 4, group_count, 1, event_type=event_type, operation_mode="DEMO"
    )
    tid = tournament["id"]
    repo.create_tables_for_tournament(conn, tid, 4)
    for index in range(1, players + 1):
        repo.add_player(conn, tid, f"选手{index:02d}", "计算机学院", 1000 + index)
    conn.commit()
    return tid


def _players(conn, tid: int) -> list[dict]:
    return repo.list_players(conn, tid)


def _two_teams(conn, tid: int, *, size_a: int = 3, size_b: int = 3) -> tuple[dict, dict]:
    players = _players(conn, tid)
    a = teams_service.create_team_entry(
        conn, tid, "A队", [p["id"] for p in players[:size_a]]
    )
    b = teams_service.create_team_entry(
        conn, tid, "B队", [p["id"] for p in players[size_a : size_a + size_b]]
    )
    return a, b


# --------------------------------------------------------------- 基础增删改查

def test_team_entry_reuses_entries_table(conn):
    tid = _create_tournament(conn)
    players = _players(conn, tid)
    team = teams_service.create_team_entry(
        conn, tid, "  计算机一队  ", [players[0]["id"], players[1]["id"], players[2]["id"]]
    )

    # 队伍就是 Entry：不新建 teams/team_members 表
    stored = repo.get_entry(conn, team["id"])
    assert stored["entry_type"] == EventType.TEAM.value
    assert stored["display_name"] == "计算机一队"  # 首尾空白被清理
    assert stored["rating_points"] == 0  # 团体赛种子未冻结：默认 0，不用队员积分推导
    assert stored["seed_no"] is None
    assert [m["player_id"] for m in stored["members"]] == [p["id"] for p in players[:3]]
    assert [m["member_order"] for m in stored["members"]] == [1, 2, 3]
    assert conn.execute("SELECT COUNT(*) FROM entry_members").fetchone()[0] == 3

    listed = teams_service.list_team_entries(conn, tid)
    assert [e["id"] for e in listed] == [team["id"]]
    assert teams_service.get_team_entry(conn, tid, team["id"])["display_name"] == "计算机一队"


def test_team_entry_accepts_explicit_rating_only(conn):
    tid = _create_tournament(conn)
    player = _players(conn, tid)[0]
    team = teams_service.create_team_entry(conn, tid, "单独积分队", [player["id"]], rating_points=1234)
    assert team["rating_points"] == 1234
    with pytest.raises(teams_service.TeamError) as excinfo:
        teams_service.create_team_entry(conn, tid, "负分队", [player["id"]], rating_points=-1)
    assert excinfo.value.code == 422


def test_team_operations_require_team_event_and_existing_tournament(conn):
    with pytest.raises(teams_service.TeamError) as missing:
        teams_service.list_team_entries(conn, 999999)
    assert missing.value.code == 404

    singles = _create_tournament(conn, event_type="SINGLES")
    player = _players(conn, singles)[0]
    with pytest.raises(teams_service.TeamError) as wrong_event:
        teams_service.create_team_entry(conn, singles, "X队", [player["id"]])
    assert wrong_event.value.code == 409
    assert "TEAM" in str(wrong_event.value)
    assert teams_service.list_team_entries(conn, singles) == []


def test_team_operations_locked_after_registration(conn):
    tid = _create_tournament(conn)
    team, _ = _two_teams(conn, tid, size_a=1, size_b=5)
    repo.update_tournament_stage(conn, tid, TournamentStage.GROUP_STAGE.value)
    conn.commit()
    player = _players(conn, tid)[0]

    for action in (
        lambda: teams_service.create_team_entry(conn, tid, "C队", [player["id"]]),
        lambda: teams_service.update_team_entry(conn, tid, team["id"], display_name="改名队"),
        lambda: teams_service.delete_team_entry(conn, tid, team["id"]),
    ):
        with pytest.raises(teams_service.TeamError) as excinfo:
            action()
        assert excinfo.value.code == 409
        assert "锁定" in str(excinfo.value)


# ------------------------------------------------------------------- 队员校验

def test_member_validation(conn):
    tid = _create_tournament(conn)
    players = _players(conn, tid)

    with pytest.raises(teams_service.TeamError) as empty:
        teams_service.create_team_entry(conn, tid, "空队", [])
    assert empty.value.code == 422
    assert "至少需要 1 名队员" in str(empty.value)

    with pytest.raises(teams_service.TeamError) as dup:
        teams_service.create_team_entry(conn, tid, "重复队", [players[0]["id"], players[0]["id"]])
    assert dup.value.code == 422

    with pytest.raises(teams_service.TeamError) as unknown:
        teams_service.create_team_entry(conn, tid, "幽灵队", [987654])
    assert unknown.value.code == 404

    first = teams_service.create_team_entry(conn, tid, "A队", [players[0]["id"]])
    with pytest.raises(teams_service.TeamError) as taken:
        teams_service.create_team_entry(conn, tid, "B队", [players[0]["id"]])
    assert taken.value.code == 409
    assert "A队" in str(taken.value)

    # 跨赛事的选手不能被拉进本赛事队伍
    other = _create_tournament(conn)
    foreign = _players(conn, other)[0]
    with pytest.raises(teams_service.TeamError) as foreign_player:
        teams_service.create_team_entry(conn, tid, "C队", [foreign["id"]])
    assert foreign_player.value.code == 404
    assert first["id"]  # 保持引用，避免未使用变量


def test_duplicate_team_name_rejected(conn):
    tid = _create_tournament(conn)
    players = _players(conn, tid)
    teams_service.create_team_entry(conn, tid, "A队", [players[0]["id"]])
    with pytest.raises(teams_service.TeamError) as excinfo:
        teams_service.create_team_entry(conn, tid, "A队", [players[1]["id"]])
    assert excinfo.value.code == 409
    assert "同名" in str(excinfo.value)


def test_update_replaces_members_and_keeps_untouched_fields(conn):
    tid = _create_tournament(conn)
    players = _players(conn, tid)
    team = teams_service.create_team_entry(conn, tid, "A队", [players[0]["id"]], rating_points=900)

    renamed = teams_service.update_team_entry(conn, tid, team["id"], display_name="A队（改）")
    assert renamed["display_name"] == "A队（改）"
    assert renamed["rating_points"] == 900
    assert [m["player_id"] for m in renamed["members"]] == [players[0]["id"]]

    replaced = teams_service.update_team_entry(
        conn, tid, team["id"], member_ids=[players[1]["id"], players[2]["id"]]
    )
    assert [m["player_id"] for m in replaced["members"]] == [players[1]["id"], players[2]["id"]]
    assert conn.execute(
        "SELECT COUNT(*) FROM entry_members WHERE entry_id = ?", (team["id"],)
    ).fetchone()[0] == 2

    # 用自己的原班人马做"全量替换"不能被当成冲突
    same = teams_service.update_team_entry(
        conn, tid, team["id"], member_ids=[players[1]["id"], players[2]["id"]]
    )
    assert len(same["members"]) == 2

    # 拉到别人队里的队员 → 409
    other = teams_service.create_team_entry(conn, tid, "B队", [players[3]["id"]])
    with pytest.raises(teams_service.TeamError) as conflict:
        teams_service.update_team_entry(conn, tid, team["id"], member_ids=[players[3]["id"]])
    assert conflict.value.code == 409
    assert "B队" in str(conflict.value)
    assert other["id"]


def test_get_team_rejects_non_team_entry(conn):
    tid = _create_tournament(conn)
    players = _players(conn, tid)
    # 直接造一个非 TEAM 的 Entity（现实中团体赛不会出现，属于防御性用例）
    singles_entry = repo.create_entry(
        conn, tid, EventType.SINGLES.value, "误入的单打实体", 0, [players[0]["id"]]
    )
    conn.commit()
    with pytest.raises(teams_service.TeamError) as excinfo:
        teams_service.get_team_entry(conn, tid, singles_entry["id"])
    assert excinfo.value.code == 409
    with pytest.raises(teams_service.TeamError) as missing:
        teams_service.get_team_entry(conn, tid, 987654)
    assert missing.value.code == 404


def test_delete_team_entry(conn):
    tid = _create_tournament(conn)
    team, _ = _two_teams(conn, tid)
    teams_service.delete_team_entry(conn, tid, team["id"])
    assert repo.get_entry(conn, team["id"]) is None
    assert conn.execute(
        "SELECT COUNT(*) FROM entry_members WHERE entry_id = ?", (team["id"],)
    ).fetchone()[0] == 0


# --------------------------------------------------------------- 名单确认三分支

def test_confirm_roster_for_team_requires_two_teams(conn):
    tid = _create_tournament(conn)
    players = _players(conn, tid)
    teams_service.create_team_entry(conn, tid, "A队", [p["id"] for p in players])
    with pytest.raises(teams_service.TeamError) as excinfo:
        entry_service.confirm_roster(conn, tid)
    assert excinfo.value.code == 409
    assert "至少需要 2 支在赛队伍" in str(excinfo.value)
    assert repo.get_tournament(conn, tid)["roster_confirmed"] == 0


def test_confirm_roster_for_team_requires_every_player_assigned(conn):
    tid = _create_tournament(conn, players=5)
    players = _players(conn, tid)
    teams_service.create_team_entry(conn, tid, "A队", [players[0]["id"], players[1]["id"]])
    teams_service.create_team_entry(conn, tid, "B队", [players[2]["id"]])
    with pytest.raises(teams_service.TeamError) as excinfo:
        entry_service.confirm_roster(conn, tid)
    assert excinfo.value.code == 409
    assert "没有加入任何队伍" in str(excinfo.value)


def test_confirm_roster_for_team_keeps_team_entries(conn):
    """确认名单只做校验与标记：绝不能像单打那样清空重建 Entry（那会把队伍删掉）。"""
    tid = _create_tournament(conn, players=6)
    a, b = _two_teams(conn, tid)
    before = {e["id"]: sorted(m["player_id"] for m in e["members"]) for e in repo.list_entries(conn, tid)}

    tournament, entries = entry_service.confirm_roster(conn, tid)

    assert tournament["roster_confirmed"] == 1
    assert tournament["confirmed_at"] is not None
    after = {e["id"]: sorted(m["player_id"] for m in e["members"]) for e in entries}
    assert after == before
    assert set(after) == {a["id"], b["id"]}
    assert all(e["entry_type"] == EventType.TEAM.value for e in entries)


def test_withdrawn_team_is_excluded_from_roster_confirmation(conn):
    """整项退赛（#14 已合入）与团体赛名单的交互：退赛队伍不能凑"至少 2 支队伍"，
    但它仍然留在名单里（队员不会被判定为"没有加入任何队伍"）。"""
    tid = _create_tournament(conn, players=4)
    a, b = _two_teams(conn, tid, size_a=2, size_b=2)
    entry_service.withdraw_from_tournament(conn, tid, b["id"], "主裁", "队伍整项退赛")
    assert repo.get_entry(conn, b["id"])["status"] == "WITHDRAWN"

    with pytest.raises(teams_service.TeamError) as excinfo:
        entry_service.confirm_roster(conn, tid)
    assert excinfo.value.code == 409
    assert "在赛队伍" in str(excinfo.value)

    # 补一支队伍后即可确认：退赛队伍不被强制删除，其他队员也不会被判为"无队"
    extra = repo.add_player(conn, tid, "替补选手", None, 1000)
    conn.commit()
    teams_service.create_team_entry(conn, tid, "C队", [extra["id"]])

    tournament, entries = entry_service.confirm_roster(conn, tid)
    assert tournament["roster_confirmed"] == 1
    statuses = {e["id"]: e["status"] for e in entries}
    assert statuses[a["id"]] == "ACTIVE"
    assert statuses[b["id"]] == "WITHDRAWN"


def test_confirm_roster_singles_and_doubles_paths_unchanged(conn):
    """三分支回归：单打仍是"重建 Entry"，双打仍是"必须两两配对"。"""
    singles = _create_tournament(conn, event_type="SINGLES", players=4)
    _, entries = entry_service.confirm_roster(conn, singles)
    assert len(entries) == 4
    assert all(e["entry_type"] == EventType.SINGLES.value and len(e["members"]) == 1 for e in entries)

    doubles = _create_tournament(conn, event_type="DOUBLES", players=4)
    with pytest.raises(entry_service.EntryError):
        entry_service.confirm_roster(conn, doubles)  # 还没配对
    entry_service.random_pair_doubles(conn, doubles, pairing_seed=7)
    _, paired = entry_service.confirm_roster(conn, doubles)
    assert len(paired) == 2
    assert all(e["entry_type"] == EventType.DOUBLES.value and len(e["members"]) == 2 for e in paired)


# ------------------------------------------------------- 二元假设回归（TEAM 保护）

def test_auto_seed_by_rating_rejects_team_and_doubles(conn):
    for event_type in ("TEAM", "DOUBLES"):
        tid = _create_tournament(conn, event_type=event_type, players=4)
        with pytest.raises(players_service.PlayerError) as excinfo:
            players_service.auto_seed_by_rating(conn, tid)
        assert excinfo.value.code == 409
        assert "尚未冻结" in str(excinfo.value)
        assert "团体赛" in str(excinfo.value)


def test_team_entry_is_never_treated_as_singles_for_seeds(conn):
    """1 人队伍不能被"成员数为 1 即单打"的旧写法播种（entries.seed_no 必须保持为空）。"""
    tid = _create_tournament(conn, players=4)
    players = _players(conn, tid)
    solo = teams_service.create_team_entry(conn, tid, "一人队", [players[0]["id"]])
    rest = teams_service.create_team_entry(
        conn, tid, "三人队", [p["id"] for p in players[1:]]
    )

    players_service.set_seeds(conn, tid, [players[0]["id"]])

    assert repo.get_entry(conn, solo["id"])["seed_no"] is None
    assert repo.get_entry(conn, rest["id"])["seed_no"] is None


def test_pair_doubles_rejects_team_tournament(conn):
    tid = _create_tournament(conn, players=6)
    with pytest.raises(entry_service.EntryError) as excinfo:
        entry_service.random_pair_doubles(conn, tid, pairing_seed=1)
    assert excinfo.value.code == 409
    assert "团体赛" in str(excinfo.value)


def test_generate_group_matches_rejects_team_tournament(conn):
    tid = _create_tournament(conn, players=6)
    _two_teams(conn, tid)
    groups_service.auto_group_tournament(conn, tid)
    with pytest.raises(matches_service.TournamentStageError) as excinfo:
        matches_service.generate_group_matches(conn, tid)
    assert "团体赛" in str(excinfo.value)
    assert repo.count_matches(conn, tid) == 0
    assert repo.get_tournament(conn, tid)["stage"] == TournamentStage.REGISTRATION.value


# --------------------------------------------------------------------- 自动分组

def test_auto_group_distributes_teams_and_marks_members(conn):
    tid = _create_tournament(conn, players=6, group_count=2)
    a, b = _two_teams(conn, tid)
    groups = groups_service.auto_group_tournament(conn, tid, rng=__import__("random").Random(3))

    assert len(groups) == 2
    group_ids = {repo.get_entry(conn, a["id"])["group_id"], repo.get_entry(conn, b["id"])["group_id"]}
    assert None not in group_ids and len(group_ids) == 2  # 两个队被分到不同组
    for group in groups:
        assert len(group["entries"]) == 1
        assert len(group["players"]) == 3
    assert all(p["group_id"] is not None for p in _players(conn, tid))


def test_auto_group_without_teams_reports_stage_error(conn):
    """名单还没准备好时必须给出 409 业务错误，而不是把 TeamError 漏成 500。"""
    tid = _create_tournament(conn, players=6)
    with pytest.raises(groups_service.TournamentStageError) as excinfo:
        groups_service.auto_group_tournament(conn, tid)
    assert "至少需要 2 支在赛队伍" in str(excinfo.value)


# ------------------------------------------------------------------- API 层

def _api_tournament(client, *, event_type: str = "TEAM", name: str = "团体赛 API") -> int:
    resp = client.post(
        "/api/tournaments",
        json={
            "name": name,
            "date": "2026-05-01",
            "table_count": 4,
            "group_count": 2,
            "qualify_per_group": 1,
            "event_type": event_type,
            "operation_mode": "DEMO",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_team_api_crud_and_errors(client):
    tid = _api_tournament(client)
    player_ids = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, 5)
    ]

    created = client.post(
        f"/api/tournaments/{tid}/teams",
        json={"display_name": "A队", "member_ids": player_ids[:2]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["entry_type"] == "TEAM"
    assert body["rating_points"] == 0
    assert [m["player_id"] for m in body["members"]] == player_ids[:2]

    second = client.post(
        f"/api/tournaments/{tid}/teams",
        json={"display_name": "B队", "member_ids": player_ids[2:]},
    )
    assert second.status_code == 201

    listed = client.get(f"/api/tournaments/{tid}/teams")
    assert listed.status_code == 200
    assert [t["display_name"] for t in listed.json()] == ["A队", "B队"]

    patched = client.patch(
        f"/api/tournaments/{tid}/teams/{body['id']}", json={"display_name": "A队（新）"}
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "A队（新）"

    assert client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "C队", "member_ids": []}
    ).status_code == 422  # Pydantic 下限
    assert client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "C队", "member_ids": [player_ids[0]]}
    ).status_code == 409  # 已被 A 队占用
    assert client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "C队", "member_ids": [999999]}
    ).status_code == 404
    assert client.get(f"/api/tournaments/{tid}/teams/999999").status_code == 404
    assert client.delete(f"/api/tournaments/999999/teams/{body['id']}").status_code == 404

    assert client.delete(f"/api/tournaments/{tid}/teams/{second.json()['id']}").status_code == 204
    assert [t["display_name"] for t in client.get(f"/api/tournaments/{tid}/teams").json()] == ["A队（新）"]


def test_team_api_rejects_singles_tournament(client):
    tid = _api_tournament(client, event_type="SINGLES")
    player = client.post(f"/api/tournaments/{tid}/players", json={"name": "单打选手"}).json()
    resp = client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "X队", "member_ids": [player["id"]]}
    )
    assert resp.status_code == 409
    assert "TEAM" in resp.json()["detail"]


def test_confirm_roster_api_for_team_returns_409_not_500(client):
    tid = _api_tournament(client)
    player_ids = [
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"}).json()["id"]
        for i in range(1, 5)
    ]
    client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "A队", "member_ids": player_ids[:2]}
    )

    resp = client.post(f"/api/tournaments/{tid}/confirm-roster")
    assert resp.status_code == 409
    assert "至少需要 2 支在赛队伍" in resp.json()["detail"]

    client.post(
        f"/api/tournaments/{tid}/teams", json={"display_name": "B队", "member_ids": player_ids[2:]}
    )
    ok = client.post(f"/api/tournaments/{tid}/confirm-roster")
    assert ok.status_code == 200, ok.text
    assert ok.json()["tournament"]["roster_confirmed"] is True
    assert [e["entry_type"] for e in ok.json()["entries"]] == ["TEAM", "TEAM"]
