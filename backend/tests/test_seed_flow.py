"""种子数据一致性 + 按积分自动种子（单打）。"""

import pytest

from app import repository as repo
from app.services import entries as entries_service
from app.services import groups as groups_service
from app.services import players as players_service


def _tournament(conn, *, players=8, group_count=4, ratings=None, event_type="SINGLES"):
    tournament = repo.create_tournament(
        conn, "种子一致性", "2025-06-01", group_count, group_count, 2,
        event_type=event_type,
    )
    tid = tournament["id"]
    created = []
    for index in range(players):
        rating = 1000 if ratings is None else ratings[index]
        created.append(repo.add_player(conn, tid, f"P{index + 1:02d}", None, rating))
    return tid, created


def _entry_seed_by_player(conn, tid):
    return {
        entry["members"][0]["player_id"]: entry["seed_no"]
        for entry in repo.list_entries(conn, tid)
        if entry["members"]
    }


def _assert_singles_entry_seeds_match_players(conn, tid):
    """不变量：单打 Entry 的种子必须等于其成员选手的种子（不允许残留旧种子）。"""
    seed_of = {p["id"]: p["seed_no"] for p in repo.list_players(conn, tid)}
    for entry in repo.list_entries(conn, tid):
        if len(entry["members"]) == 1:
            assert entry["seed_no"] == seed_of[entry["members"][0]["player_id"]]


def test_demo_generated_seeds_stay_in_sync_with_entries(conn):
    """DEMO 生成演示选手（自动种子）：Entry 不得残留旧种子，重新确认名单后按新种子分散。"""
    tid, players = _tournament(conn, players=8, ratings=[1000 + index for index in range(8)])
    entries_service.confirm_roster(conn, tid)
    players_service.set_seeds(conn, tid, [p["id"] for p in players[:4]])
    assert _entry_seed_by_player(conn, tid)[players[0]["id"]] == 1

    players_service.generate_demo_players(conn, tid, 4, True)

    seed_of = {p["id"]: p["seed_no"] for p in repo.list_players(conn, tid)}
    old_ids = {p["id"] for p in players}
    seeded = sorted(
        (pid for pid, seed in seed_of.items() if seed is not None),
        key=lambda pid: seed_of[pid],
    )
    assert len(seeded) == 4
    assert all(seed_of[pid] is None for pid in old_ids)          # 旧选手种子被清空
    _assert_singles_entry_seeds_match_players(conn, tid)          # 旧 Entry 种子不得残留

    # 名单重新确认 → Entry 按新种子重建 → 自动分组使用新种子
    entries_service.confirm_roster(conn, tid)
    _assert_singles_entry_seeds_match_players(conn, tid)
    entry_seeds = _entry_seed_by_player(conn, tid)
    assert [entry_seeds[pid] for pid in seeded] == [1, 2, 3, 4]

    groups = groups_service.auto_group_tournament(conn, tid)
    name_of = {group["id"]: group["name"] for group in groups}
    group_of = {p["id"]: p["group_id"] for p in repo.list_players(conn, tid)}
    assert [name_of[group_of[pid]] for pid in seeded] == ["A组", "B组", "C组", "D组"]


def test_seed_change_after_roster_confirmation_is_used_by_grouping(conn):
    """确认名单后改种子：Entry 必须同步，自动分组必须按新种子分散。"""
    tid, players = _tournament(conn)
    entries_service.confirm_roster(conn, tid)
    assert set(_entry_seed_by_player(conn, tid).values()) == {None}

    ranked = [players[7]["id"], players[6]["id"], players[5]["id"], players[4]["id"]]
    players_service.set_seeds(conn, tid, ranked)

    seed_of = {p["id"]: p["seed_no"] for p in repo.list_players(conn, tid)}
    assert [seed_of[pid] for pid in ranked] == [1, 2, 3, 4]
    entry_seeds = _entry_seed_by_player(conn, tid)
    assert {entry_seeds[pid] for pid in ranked} == {1, 2, 3, 4}
    assert all(
        entry_seeds[pid] is None
        for pid in seed_of
        if pid not in ranked
    )

    groups = groups_service.auto_group_tournament(conn, tid)
    group_of = {p["id"]: p["group_id"] for p in repo.list_players(conn, tid)}
    assert len({group_of[pid] for pid in ranked}) == 4  # 四名种子分散到四个小组
    name_of = {group["id"]: group["name"] for group in groups}
    assert [name_of[group_of[pid]] for pid in ranked] == ["A组", "B组", "C组", "D组"]


def test_seed_before_roster_confirmation_survives_confirmation(conn):
    tid, players = _tournament(conn)
    ranked = [players[2]["id"], players[0]["id"]]
    players_service.set_seeds(conn, tid, ranked)

    entries_service.confirm_roster(conn, tid)

    entry_seeds = _entry_seed_by_player(conn, tid)
    assert entry_seeds[ranked[0]] == 1
    assert entry_seeds[ranked[1]] == 2


def test_reorder_and_clear_seeds_keep_entries_in_sync(conn):
    tid, players = _tournament(conn)
    entries_service.confirm_roster(conn, tid)
    first, second = players[0]["id"], players[1]["id"]

    players_service.set_seeds(conn, tid, [first, second])
    assert _entry_seed_by_player(conn, tid)[first] == 1

    players_service.set_seeds(conn, tid, [second, first])
    entry_seeds = _entry_seed_by_player(conn, tid)
    assert entry_seeds[second] == 1 and entry_seeds[first] == 2

    players_service.set_seeds(conn, tid, [])
    assert {v for v in entry_seeds.values() if v is not None} == {1, 2}
    assert set(_entry_seed_by_player(conn, tid).values()) == {None}
    assert all(p["seed_no"] is None for p in repo.list_players(conn, tid))


def test_auto_seed_by_rating_uses_points_then_id(conn):
    """按积分自动种子：积分降序，同分按 id 升序，默认取 group_count 名。"""
    ratings = [2000, 1900, 1800, 1700, 1700, 1600, 1500, 1400]
    tid, players = _tournament(conn, ratings=ratings)
    entries_service.confirm_roster(conn, tid)

    players_service.auto_seed_by_rating(conn, tid)

    expected = [
        players[0]["id"],  # 2000
        players[1]["id"],  # 1900
        players[2]["id"],  # 1800
        players[3]["id"],  # 1700（与 players[4] 同分，id 更小）
    ]
    seed_of = {p["id"]: p["seed_no"] for p in repo.list_players(conn, tid)}
    assert [seed_of[pid] for pid in expected] == [1, 2, 3, 4]
    assert seed_of[players[4]["id"]] is None
    entry_seeds = _entry_seed_by_player(conn, tid)
    assert [entry_seeds[pid] for pid in expected] == [1, 2, 3, 4]

    # 生成后仍可手工调整（自动 ≠ 永久覆盖）
    players_service.set_seeds(conn, tid, [players[7]["id"]])
    seed_of = {p["id"]: p["seed_no"] for p in repo.list_players(conn, tid)}
    assert seed_of[players[7]["id"]] == 1
    assert seed_of[players[0]["id"]] is None


def test_auto_seed_then_auto_group_disperses_by_rating(conn):
    """场景 7：4 组 8 人，2000/1900/1800/1700 四人成为 S1-S4 并分散四组。"""
    ratings = [2000, 1900, 1800, 1700, 1600, 1500, 1400, 1300]
    tid, players = _tournament(conn, ratings=ratings)
    entries_service.confirm_roster(conn, tid)
    players_service.auto_seed_by_rating(conn, tid)

    groups = groups_service.auto_group_tournament(conn, tid)

    group_of = {p["id"]: p["group_id"] for p in repo.list_players(conn, tid)}
    seeded = [p["id"] for p in players[:4]]
    assert len({group_of[pid] for pid in seeded}) == 4
    name_of = {group["id"]: group["name"] for group in groups}
    assert [name_of[group_of[pid]] for pid in seeded] == ["A组", "B组", "C组", "D组"]


def test_auto_seed_rejects_doubles(conn):
    tid, _ = _tournament(conn, players=8, group_count=2, event_type="DOUBLES")
    with pytest.raises(players_service.PlayerError) as excinfo:
        players_service.auto_seed_by_rating(conn, tid)
    assert excinfo.value.code == 409
    assert "双打" in str(excinfo.value)


def test_auto_seed_locked_after_group_stage(conn):
    tid, _ = _tournament(conn)
    repo.update_tournament_stage(conn, tid, "GROUP_STAGE")
    with pytest.raises(players_service.PlayerError) as excinfo:
        players_service.auto_seed_by_rating(conn, tid)
    assert excinfo.value.code == 409


def test_api_auto_seed_endpoint(client):
    tid = client.post(
        "/api/tournaments",
        json={
            "name": "自动种子",
            "date": "2025-06-01",
            "table_count": 4,
            "group_count": 4,
            "qualify_per_group": 2,
        },
    ).json()["id"]
    for index in range(8):
        client.post(
            f"/api/tournaments/{tid}/players",
            json={"name": f"P{index + 1}", "rating_points": 2000 - index * 100},
        )
    client.post(f"/api/tournaments/{tid}/confirm-roster")

    resp = client.post(f"/api/tournaments/{tid}/seeds/auto")

    assert resp.status_code == 200
    seeded = {p["name"]: p["seed_no"] for p in resp.json()}
    assert [seeded[f"P{i}"] for i in range(1, 5)] == [1, 2, 3, 4]
    assert all(seeded[f"P{i}"] is None for i in range(5, 9))

    entries = client.get(f"/api/tournaments/{tid}/entries").json()
    assert [entry["seed_no"] for entry in entries].count(1) == 1
    assert sorted(e["seed_no"] for e in entries if e["seed_no"] is not None) == [1, 2, 3, 4]
