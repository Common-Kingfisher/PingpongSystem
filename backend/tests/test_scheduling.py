"""比赛状态 + 球台调度测试：状态机、硬约束、一致性不变量。"""

from collections import Counter

from app import repository as repo
from app.models import MatchStage, MatchStatus, TableStatus
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import scheduling as scheduling_service


def _tournament_with_matches(client, n_players=24, group_count=4, table_count=6):
    resp = client.post(
        "/api/tournaments",
        json={
            "name": "调度测试赛",
            "date": "2025-06-01",
            "table_count": table_count,
            "group_count": group_count,
            "qualify_per_group": 2,
        },
    )
    tid = resp.json()["id"]
    for i in range(1, n_players + 1):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i:02d}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    return tid


def _service_tournament(conn, n_players=24, table_count=6, group_count=4) -> int:
    """服务级测试用：建赛事（含球台）→ 加选手 → 分组 → 生成小组赛。"""
    t = repo.create_tournament(conn, "T", "2025-06-01", table_count, group_count, 2)
    repo.create_tables_for_tournament(conn, t["id"], table_count)
    for i in range(1, n_players + 1):
        repo.add_player(conn, t["id"], f"P{i}", None)
    groups_service.auto_group_tournament(conn, t["id"])
    matches_service.generate_group_matches(conn, t["id"])
    return t["id"]


def _assert_invariants(conn, tid):
    """一致性不变量：PLAYING 数 == OCCUPIED 数；无人同时两场 PLAYING。"""
    matches = repo.list_matches(conn, tid)
    playing = [m for m in matches if m["status"] == MatchStatus.PLAYING.value]
    occupied = sum(
        1 for t in repo.list_tables(conn, tid)
        if t["status"] == TableStatus.OCCUPIED.value
    )
    assert len(playing) == occupied
    counts = Counter()
    for m in playing:
        counts[m["player_a_id"]] += 1
        counts[m["player_b_id"]] += 1
    assert all(v == 1 for v in counts.values()), "存在选手同时参加两场比赛"


# ------------------------------------------------------------------ 服务层

def test_assign_table_happy_path(conn):
    tid = _service_tournament(conn)
    waiting = [m for m in repo.list_matches(conn, tid) if m["status"] == "WAITING"]
    match = waiting[0]
    table = repo.list_tables(conn, tid)[0]

    updated = scheduling_service.assign_table(conn, match["id"], table["id"])
    assert updated["status"] == "PLAYING"
    assert updated["table_id"] == table["id"]
    assert repo.get_table(conn, table["id"])["status"] == "OCCUPIED"
    _assert_invariants(conn, tid)


def test_assign_table_rejects_same_match_twice(conn):
    tid = _service_tournament(conn, n_players=6)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    try:
        scheduling_service.assign_table(conn, match["id"], table["id"])
        assert False, "应当拒绝重复安排"
    except scheduling_service.SchedulingError as exc:
        assert exc.code == 409


def test_assign_table_rejects_player_conflict(conn):
    # 单组 6 人：P1 将出战 5 场，存在跨轮共享选手的 WAITING 比赛
    tid = _service_tournament(conn, n_players=6, group_count=1)
    matches = repo.list_matches(conn, tid)
    table = repo.list_tables(conn, tid)[0]
    # 第 1 场先上球台
    first = matches[0]
    scheduling_service.assign_table(conn, first["id"], table["id"])
    # 找一场包含 first.player_a 的 WAITING 比赛（跨轮共享选手）
    conflict = next(
        m for m in matches
        if m["id"] != first["id"]
        and m["status"] == "WAITING"
        and first["player_a_id"] in (m["player_a_id"], m["player_b_id"])
    )
    free_table = next(
        t2 for t2 in repo.list_tables(conn, tid)
        if t2["status"] == "FREE"
    )
    try:
        scheduling_service.assign_table(conn, conflict["id"], free_table["id"])
        assert False, "应当拒绝选手冲突安排"
    except scheduling_service.SchedulingError:
        pass


def test_assign_table_rejects_finished_match(conn):
    # 任务 5 之前没有录分入口；用 repository 直接置 FINISHED 模拟
    tid = _service_tournament(conn, n_players=6)
    match = repo.list_matches(conn, tid)[0]
    repo.update_match(conn, match["id"], status="FINISHED", player_a_score=3, player_b_score=0, winner_id=match["player_a_id"])
    table = repo.list_tables(conn, tid)[0]
    try:
        scheduling_service.assign_table(conn, match["id"], table["id"])
        assert False, "已结束比赛不可再安排"
    except scheduling_service.SchedulingError:
        pass


def test_schedule_next_batch(conn):
    tid = _service_tournament(conn)
    assignments = scheduling_service.schedule_next(conn, tid)
    assert len(assignments) == 6  # 6 张空闲球台
    assert len(set(a[1] for a in assignments)) == 6  # 球台不重复
    _assert_invariants(conn, tid)

    # 没有空闲球台时不再分配
    assert scheduling_service.schedule_next(conn, tid) == []


# ------------------------------------------------ 小组-球台优先（软约束）

def test_group_table_affinity_maps_groups_to_tables_in_order(conn):
    tid = _service_tournament(conn, n_players=24, group_count=4, table_count=4)
    groups = repo.list_groups(conn, tid)
    tables = repo.list_tables(conn, tid)
    affinity = scheduling_service.group_table_affinity(conn, tid)
    assert [affinity[g["id"]] for g in groups] == [t["id"] for t in tables]


def test_group_table_affinity_wraps_when_more_groups_than_tables(conn):
    tid = _service_tournament(conn, n_players=12, group_count=6, table_count=2)
    groups = repo.list_groups(conn, tid)
    tables = repo.list_tables(conn, tid)
    affinity = scheduling_service.group_table_affinity(conn, tid)
    assert len(affinity) == 6
    assert [affinity[g["id"]] for g in groups] == [
        tables[i % 2]["id"] for i in range(6)
    ]


def test_group_table_affinity_empty_without_tables(conn):
    tid = _service_tournament(conn, n_players=6, group_count=2, table_count=1)
    conn.execute("DELETE FROM tables WHERE tournament_id = ?", (tid,))
    conn.commit()
    assert repo.list_tables(conn, tid) == []
    assert scheduling_service.group_table_affinity(conn, tid) == {}
    assert scheduling_service.schedule_next(conn, tid) == []


def test_schedule_next_puts_each_group_on_its_own_table(conn):
    tid = _service_tournament(conn, n_players=24, group_count=4, table_count=4)
    affinity = scheduling_service.group_table_affinity(conn, tid)
    group_of = {m["id"]: m["group_id"] for m in repo.list_matches(conn, tid)}

    assignments = scheduling_service.schedule_next(conn, tid)

    assert len(assignments) == 4
    for match_id, table_id in assignments:
        assert affinity[group_of[match_id]] == table_id
    _assert_invariants(conn, tid)


def test_schedule_next_falls_back_when_preferred_group_has_no_match(conn):
    tid = _service_tournament(conn, n_players=24, group_count=4, table_count=4)
    affinity = scheduling_service.group_table_affinity(conn, tid)
    group_of = {m["id"]: m["group_id"] for m in repo.list_matches(conn, tid)}
    first_group = repo.list_groups(conn, tid)[0]
    for m in repo.list_matches(conn, tid, group_id=first_group["id"]):
        repo.update_match(
            conn,
            m["id"],
            status=MatchStatus.FINISHED.value,
            player_a_score=3,
            player_b_score=0,
            winner_id=m["player_a_id"],
        )

    assignments = scheduling_service.schedule_next(conn, tid)

    # 软约束：专属小组没比赛时球台不空转，回退安排其他小组的比赛
    assert len(assignments) == 4
    preferred_table = affinity[first_group["id"]]
    fallback_match = next(mid for mid, table_id in assignments if table_id == preferred_table)
    assert group_of[fallback_match] != first_group["id"]
    _assert_invariants(conn, tid)


def test_schedule_next_affinity_beats_match_id_order(conn):
    """group_id 为 None 的淘汰赛比赛没有偏好球台，即使 id 更小也排在小组赛之后。"""
    t = repo.create_tournament(conn, "T", "2025-06-01", 2, 1, 2)
    repo.create_tables_for_tournament(conn, t["id"], 2)
    players = [repo.add_player(conn, t["id"], f"P{i}", None) for i in range(1, 5)]
    knockout = repo.create_match(
        conn, t["id"], MatchStage.KNOCKOUT.value, None, 1, 1,
        players[0]["id"], players[1]["id"],
    )
    groups_service.auto_group_tournament(conn, t["id"])
    matches_service.generate_group_matches(conn, t["id"])

    affinity = scheduling_service.group_table_affinity(conn, t["id"])
    assert None not in affinity
    group = repo.list_groups(conn, t["id"])[0]
    preferred_table = affinity[group["id"]]

    assignments = scheduling_service.schedule_next(conn, t["id"])

    chosen = dict((table_id, match_id) for match_id, table_id in assignments)
    assert chosen[preferred_table] != knockout["id"]
    assert repo.get_match(conn, chosen[preferred_table])["group_id"] == group["id"]
    _assert_invariants(conn, t["id"])


def test_release_match_frees_table(conn):
    tid = _service_tournament(conn, n_players=6)
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])

    updated = scheduling_service.release_match(conn, match["id"])
    assert updated["status"] == "WAITING"
    assert updated["table_id"] is None
    assert repo.get_table(conn, table["id"])["status"] == "FREE"
    _assert_invariants(conn, tid)


def test_release_waiting_match_rejected(conn):
    tid = _service_tournament(conn, n_players=6)
    match = repo.list_matches(conn, tid)[0]
    try:
        scheduling_service.release_match(conn, match["id"])
        assert False, "WAITING 比赛不可下球台"
    except scheduling_service.SchedulingError:
        pass


def test_dashboard_counts_and_next_playable(conn):
    tid = _service_tournament(conn)
    data = scheduling_service.get_dashboard(conn, tid)
    assert data["stats"] == {"total": 60, "finished": 0, "playing": 0, "waiting": 60}
    assert len(data["tables"]) == 6
    assert all(tbl["status"] == "FREE" and tbl["match"] is None for tbl in data["tables"])
    assert len(data["next_playable"]) == 60

    scheduling_service.schedule_next(conn, tid)
    data = scheduling_service.get_dashboard(conn, tid)
    assert data["stats"]["playing"] == 6
    assert data["stats"]["waiting"] == 54
    occupied = [tbl for tbl in data["tables"] if tbl["status"] == "OCCUPIED"]
    assert len(occupied) == 6
    assert all(tbl["match"] is not None and tbl["match"]["status"] == "PLAYING" for tbl in occupied)
    # next_playable 不再包含进行中选手的比赛
    playing_players = set()
    for tbl in occupied:
        playing_players.add(tbl["match"]["player_a_id"])
        playing_players.add(tbl["match"]["player_b_id"])
    for m in data["next_playable"]:
        assert m["player_a_id"] not in playing_players
        assert m["player_b_id"] not in playing_players


# ---------------------------------------------------------------------- API

def test_api_assign_and_release(client):
    tid = _tournament_with_matches(client)
    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    table = client.get(f"/api/tournaments/{tid}/dashboard").json()["tables"][0]
    m = matches[0]

    resp = client.post(f"/api/matches/{m['id']}/assign-table", json={"table_id": table["id"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "PLAYING"

    # 重复安排 → 409
    resp = client.post(f"/api/matches/{m['id']}/assign-table", json={"table_id": table["id"]})
    assert resp.status_code == 409

    resp = client.post(f"/api/matches/{m['id']}/release")
    assert resp.status_code == 200
    assert resp.json()["status"] == "WAITING"


def test_api_schedule_next(client):
    tid = _tournament_with_matches(client)
    resp = client.post(f"/api/tournaments/{tid}/schedule-next")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assigned"] == 6
    assert len(data["assignments"]) == 6

    dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert dash["stats"]["playing"] == 6
    assert dash["stats"]["waiting"] == 54


def test_api_schedule_next_prefers_group_tables(client):
    tid = _tournament_with_matches(client, n_players=24, group_count=4, table_count=4)
    resp = client.post(f"/api/tournaments/{tid}/schedule-next")
    assert resp.status_code == 200
    data = resp.json()
    assert data["assigned"] == 4

    groups = client.get(f"/api/tournaments/{tid}/groups").json()["groups"]
    tables = client.get(f"/api/tournaments/{tid}/dashboard").json()["tables"]
    matches = {m["id"]: m for m in client.get(f"/api/tournaments/{tid}/matches").json()}
    expected = {g["id"]: tables[i % len(tables)]["id"] for i, g in enumerate(groups)}
    for item in data["assignments"]:
        assert expected[matches[item["match_id"]]["group_id"]] == item["table_id"]


def test_api_dashboard(client):
    tid = _tournament_with_matches(client)
    resp = client.get(f"/api/tournaments/{tid}/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stats"]["total"] == 60
    assert len(data["tables"]) == 6
    assert len(data["next_playable"]) == 60


def test_api_assign_missing_table_404(client):
    tid = _tournament_with_matches(client)
    m = client.get(f"/api/tournaments/{tid}/matches").json()[0]
    resp = client.post(f"/api/matches/{m['id']}/assign-table", json={"table_id": 999})
    assert resp.status_code == 404
