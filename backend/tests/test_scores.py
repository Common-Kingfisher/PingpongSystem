"""比分录入/修改测试：胜者正确、平局/负数拒绝、状态守卫、修改不累计污染、排名联动。"""

from app import repository as repo
from app.models import MatchStatus, TableStatus
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import rankings as rankings_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service


def _service_tournament(conn, n_players=6, table_count=6, group_count=1):
    t = repo.create_tournament(conn, "T", "2025-06-01", table_count, group_count, 2)
    repo.create_tables_for_tournament(conn, t["id"], table_count)
    for i in range(1, n_players + 1):
        repo.add_player(conn, t["id"], f"P{i}", None)
    groups_service.auto_group_tournament(conn, t["id"])
    matches_service.generate_group_matches(conn, t["id"])
    return t["id"]


def _assign_first(conn, tid):
    match = repo.list_matches(conn, tid)[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, match["id"], table["id"])
    return match, table


# ------------------------------------------------------------------ 服务层

def test_record_score_finishes_and_frees_table(conn):
    tid = _service_tournament(conn)
    match, table = _assign_first(conn, tid)

    updated = scores_service.record_score(conn, match["id"], 3, 1)
    assert updated["status"] == "FINISHED"
    assert updated["player_a_score"] == 3
    assert updated["player_b_score"] == 1
    assert updated["winner_id"] == match["player_a_id"]
    assert repo.get_table(conn, table["id"])["status"] == "FREE"


def test_record_score_winner_side_b(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    updated = scores_service.record_score(conn, match["id"], 2, 3)
    assert updated["winner_id"] == match["player_b_id"]


def test_record_score_draw_rejected(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    try:
        scores_service.record_score(conn, match["id"], 3, 3)
        assert False, "平局应被拒绝"
    except scores_service.ScoreError as exc:
        assert exc.code == 409


def test_record_score_on_waiting_allowed(conn):
    """放宽后：WAITING（未上球台）且双方就绪也可直接出结果（供淘汰赛页直接录分）。"""
    tid = _service_tournament(conn)
    match = repo.list_matches(conn, tid)[0]
    updated = scores_service.record_score(conn, match["id"], 3, 1)
    assert updated["status"] == "FINISHED"
    assert updated["winner_id"] == match["player_a_id"]


def test_record_score_on_finished_rejected(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    scores_service.record_score(conn, match["id"], 3, 1)
    try:
        scores_service.record_score(conn, match["id"], 3, 0)
        assert False, "FINISHED 不可重复录分"
    except scores_service.ScoreError:
        pass


def test_revise_score_flips_winner(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    scores_service.record_score(conn, match["id"], 3, 1)
    assert repo.get_match(conn, match["id"])["winner_id"] == match["player_a_id"]

    updated = scores_service.revise_score(conn, match["id"], 2, 3)
    assert updated["winner_id"] == match["player_b_id"]
    assert updated["status"] == "FINISHED"


def test_revise_on_playing_rejected(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    try:
        scores_service.revise_score(conn, match["id"], 3, 1)
        assert False, "PLAYING 不可改分"
    except scores_service.ScoreError:
        pass


def test_revise_no_pollution(conn):
    """连续多次改分后，排名只反映最终结果，不累计中间状态。"""
    tid = _service_tournament(conn, n_players=4)
    matches = repo.list_matches(conn, tid)
    # 三场：1v2, 1v3, 2v3（选手有重叠，直接置 PLAYING 绕过调度约束——本测试只关心比分语义）
    m12 = next(m for m in matches if {m["player_a_id"], m["player_b_id"]} == {1, 2})
    m13 = next(m for m in matches if {m["player_a_id"], m["player_b_id"]} == {1, 3})
    m23 = next(m for m in matches if {m["player_a_id"], m["player_b_id"]} == {2, 3})
    for m in (m12, m13, m23):
        repo.update_match(conn, m["id"], status="PLAYING")

    scores_service.record_score(conn, m12["id"], 3, 0)   # 1 胜 2
    scores_service.record_score(conn, m13["id"], 0, 3)   # 3 胜 1
    scores_service.record_score(conn, m23["id"], 3, 0)   # 2 胜 3
    # 胜场：1=1, 2=1, 3=1，净胜局同为 0 → 3 人并列
    entries_before = rankings_service.get_rankings(conn, tid)[0]["entries"]
    assert sorted(e["wins"] for e in entries_before) == [0, 1, 1, 1]

    # 修改 m12：1 胜 2 → 2 胜 1；修改 m23：2 胜 3 → 3 胜 2
    scores_service.revise_score(conn, m12["id"], 2, 3)
    scores_service.revise_score(conn, m23["id"], 1, 3)
    # 最终：3 胜 1(3:0) 胜 2(3:1) → 2 胜；2 胜 1(3:2) → 1 胜；
    # 1 与 4 同为 0 胜：4 净胜局 0 > 1 的 -4 → 4 在前
    entries = rankings_service.get_rankings(conn, tid)[0]["entries"]
    by_pid = {e["player_id"]: e for e in entries}
    assert by_pid[3]["wins"] == 2
    assert by_pid[2]["wins"] == 1
    assert by_pid[1]["wins"] == 0
    # 关键：即使中间状态是"1 胜 2"，最终排名只由最终比分决定
    assert [e["player_id"] for e in entries] == [3, 2, 4, 1]


def _free_table(conn, tid):
    return next(t for t in repo.list_tables(conn, tid) if t["status"] == "FREE")


# ---------------------------------------------------------------------- API

def test_api_score_flow(client):
    resp = client.post(
        "/api/tournaments",
        json={"name": "S", "date": "2025-06-01", "table_count": 6, "group_count": 1, "qualify_per_group": 2},
    )
    tid = resp.json()["id"]
    for i in range(1, 5):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"P{i}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    matches = client.get(f"/api/tournaments/{tid}/matches").json()
    tables = client.get(f"/api/tournaments/{tid}/dashboard").json()["tables"]

    # 安排 + 录分
    resp = client.post(f"/api/matches/{matches[0]['id']}/assign-table", json={"table_id": tables[0]["id"]})
    assert resp.status_code == 200
    resp = client.post(
        f"/api/matches/{matches[0]['id']}/score",
        json={"player_a_score": 3, "player_b_score": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "FINISHED"
    assert data["winner_id"] == matches[0]["player_a_id"]

    # 平局 422（pydantic 层不拦，服务层 409）
    resp = client.post(
        f"/api/matches/{matches[0]['id']}/revise-score",
        json={"player_a_score": 2, "player_b_score": 2},
    )
    assert resp.status_code == 409

    # 负数 422
    resp = client.post(
        f"/api/matches/{matches[0]['id']}/revise-score",
        json={"player_a_score": -1, "player_b_score": 3},
    )
    assert resp.status_code == 422

    # 改分
    resp = client.post(
        f"/api/matches/{matches[0]['id']}/revise-score",
        json={"player_a_score": 1, "player_b_score": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["winner_id"] == matches[0]["player_b_id"]


def test_api_rankings_shape(client):
    resp = client.post(
        "/api/tournaments",
        json={"name": "R", "date": "2025-06-01", "table_count": 6, "group_count": 2, "qualify_per_group": 2},
    )
    tid = resp.json()["id"]
    for i in range(1, 9):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    resp = client.get(f"/api/tournaments/{tid}/rankings")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rankings"]) == 2
    for g in data["rankings"]:
        assert g["total_matches"] == 6  # 4 人组
        assert g["finished_matches"] == 0
        assert len(g["entries"]) == 4
        e0 = g["entries"][0]
        assert set(e0.keys()) >= {"player_id", "name", "wins", "losses", "games_won", "games_lost", "rank", "tied", "qualified"}


def test_api_rankings_after_scores(client):
    resp = client.post(
        "/api/tournaments",
        json={"name": "R2", "date": "2025-06-01", "table_count": 6, "group_count": 1, "qualify_per_group": 2},
    )
    tid = resp.json()["id"]
    for i in range(1, 5):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")

    # 按轮次循环：批量调度 → 录分 → 再调度，直到全部结束（选手1 全胜）
    for _ in range(6):
        client.post(f"/api/tournaments/{tid}/schedule-next")
        dash = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [tb["match"] for tb in dash["tables"] if tb["match"]]
        if not playing:
            break
        for m in playing:
            a_id, b_id = m["player_a_id"], m["player_b_id"]
            if a_id == 1:
                sa, sb = 3, 0
            elif b_id == 1:
                sa, sb = 0, 3
            else:
                sa, sb = 3, 1
            client.post(f"/api/matches/{m['id']}/score", json={"player_a_score": sa, "player_b_score": sb})

    data = client.get(f"/api/tournaments/{tid}/rankings").json()
    g = data["rankings"][0]
    assert g["finished_matches"] == 6
    top = g["entries"][0]
    assert top["player_id"] == 1
    assert top["wins"] == 3
    assert top["qualified"] is True
    # 选手 2/3/4 形成循环胜负（各 1 胜、净胜局同为 -3）→ 并列歧义：
    # 系统诚实标记 ambiguous，只保证选手 1 晋级，不编造第二名
    assert g["ambiguous_qualification"] is True
    assert [e["player_id"] for e in g["entries"] if e["qualified"]] == [1]
    tied_at_cutoff = [e["player_id"] for e in g["entries"] if e["tied"]]
    assert sorted(tied_at_cutoff) == [2, 3, 4]
