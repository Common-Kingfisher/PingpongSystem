"""比分录入/修改测试：胜者正确、平局/负数拒绝、状态守卫、修改不累计污染、排名联动。"""

import pytest

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

    updated = scores_service.record_score(conn, match["id"], 2, 1)
    assert updated["status"] == "FINISHED"
    assert updated["player_a_score"] == 2
    assert updated["player_b_score"] == 1
    assert updated["winner_id"] == match["player_a_id"]
    assert repo.get_table(conn, table["id"])["status"] == "FREE"


def test_record_score_winner_side_b(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    updated = scores_service.record_score(conn, match["id"], 1, 2)
    assert updated["winner_id"] == match["player_b_id"]


def test_record_score_draw_rejected(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    try:
        scores_service.record_score(conn, match["id"], 2, 2)
        assert False, "平局应被拒绝"
    except scores_service.ScoreError as exc:
        assert exc.code == 409


def test_record_score_on_waiting_allowed(conn):
    """放宽后：WAITING（未上球台）且双方就绪也可直接出结果（供淘汰赛页直接录分）。"""
    tid = _service_tournament(conn)
    match = repo.list_matches(conn, tid)[0]
    updated = scores_service.record_score(conn, match["id"], 2, 1)
    assert updated["status"] == "FINISHED"
    assert updated["winner_id"] == match["player_a_id"]


def test_record_score_on_finished_rejected(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    scores_service.record_score(conn, match["id"], 2, 1)
    try:
        scores_service.record_score(conn, match["id"], 2, 0)
        assert False, "FINISHED 不可重复录分"
    except scores_service.ScoreError:
        pass


def test_revise_score_flips_winner(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    scores_service.record_score(conn, match["id"], 2, 1)
    assert repo.get_match(conn, match["id"])["winner_id"] == match["player_a_id"]

    updated = scores_service.revise_score(conn, match["id"], 1, 2)
    assert updated["winner_id"] == match["player_b_id"]
    assert updated["status"] == "FINISHED"


def test_revise_on_playing_rejected(conn):
    tid = _service_tournament(conn)
    match, _ = _assign_first(conn, tid)
    try:
        scores_service.revise_score(conn, match["id"], 2, 1)
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

    scores_service.record_score(conn, m12["id"], 2, 0)   # 1 胜 2
    scores_service.record_score(conn, m13["id"], 0, 2)   # 3 胜 1
    scores_service.record_score(conn, m23["id"], 2, 0)   # 2 胜 3
    # 胜场：1=1, 2=1, 3=1，净胜局同为 0 → 3 人并列
    entries_before = rankings_service.get_rankings(conn, tid)[0]["entries"]
    assert sorted(e["wins"] for e in entries_before) == [0, 1, 1, 1]

    # 修改 m12：1 胜 2 → 2 胜 1；修改 m23：2 胜 3 → 3 胜 2
    scores_service.revise_score(conn, m12["id"], 1, 2)
    scores_service.revise_score(conn, m23["id"], 1, 2)
    # 最终：3 胜 1(2:0) 胜 2(2:1) → 2 胜；2 胜 1(2:1) → 1 胜；
    # 1 与 4 同为 0 胜：4 净胜局 0 > 1 的 -3 → 4 在前
    entries = rankings_service.get_rankings(conn, tid)[0]["entries"]
    by_pid = {e["player_id"]: e for e in entries}
    assert by_pid[3]["wins"] == 2
    assert by_pid[2]["wins"] == 1
    assert by_pid[1]["wins"] == 0
    # 关键：即使中间状态是"1 胜 2"，最终排名只由最终比分决定
    assert [e["player_id"] for e in entries] == [3, 2, 4, 1]


def test_group_tie_requests_small_scores_then_resolves_by_point_ratio(conn):
    """常规只录大比分；三人循环同分时才请求并使用相关比赛小分。"""
    tid = _service_tournament(conn, n_players=3, group_count=1)
    matches = repo.list_matches(conn, tid)

    # P1 胜 P2、P2 胜 P3、P3 胜 P1，且均为 2:1：胜场、净胜局、积分完全相同。
    outcomes = {
        frozenset((1, 2)): (1, [(11, 1), (1, 11), (11, 1)]),
        frozenset((2, 3)): (2, [(11, 5), (5, 11), (11, 5)]),
        frozenset((1, 3)): (3, [(11, 9), (9, 11), (11, 9)]),
    }
    for match in matches:
        a, b = match["player_a_id"], match["player_b_id"]
        winner, canonical_games = outcomes[frozenset((a, b))]
        if a == winner:
            score = (2, 1)
        else:
            score = (1, 2)
        scores_service.record_score(conn, match["id"], *score)

    before = rankings_service.get_rankings(conn, tid)[0]
    assert before["ambiguous_qualification"] is True
    assert before["needs_point_scores"] is True
    assert sorted(before["point_score_match_ids"]) == sorted(m["id"] for m in matches)

    for match in matches:
        a, b = match["player_a_id"], match["player_b_id"]
        winner, canonical_games = outcomes[frozenset((a, b))]
        # canonical_games 是“胜者:负者”，按数据库 A/B 方向翻转。
        games = canonical_games if a == winner else [(right, left) for left, right in canonical_games]
        score = (2, 1) if a == winner else (1, 2)
        scores_service.revise_score(conn, match["id"], *score, games=games)

    after = rankings_service.get_rankings(conn, tid)[0]
    assert after["needs_point_scores"] is False
    assert after["ambiguous_qualification"] is False
    assert [entry["player_id"] for entry in after["entries"]] == [1, 3, 2]


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
        json={"player_a_score": 2, "player_b_score": 1},
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
        json={"player_a_score": 1, "player_b_score": 2},
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
                sa, sb = 2, 0
            elif b_id == 1:
                sa, sb = 0, 2
            else:
                sa, sb = 2, 1
            client.post(f"/api/matches/{m['id']}/score", json={"player_a_score": sa, "player_b_score": sb})

    data = client.get(f"/api/tournaments/{tid}/rankings").json()
    g = data["rankings"][0]
    assert g["finished_matches"] == 6
    top = g["entries"][0]
    assert top["player_id"] == 1
    assert top["wins"] == 3
    assert top["qualified"] is True
    # 选手 2/3/4 形成循环胜负（各 1 胜、净胜局同为 -2）→ 并列歧义：
    # 系统诚实标记 ambiguous，只保证选手 1 晋级，不编造第二名
    assert g["ambiguous_qualification"] is True
    assert [e["player_id"] for e in g["entries"] if e["qualified"]] == [1]
    tied_at_cutoff = [e["player_id"] for e in g["entries"] if e["tied"]]
    assert sorted(tied_at_cutoff) == [2, 3, 4]


# ------------------------------------------------------------------ 比分规则反例（B1-A / B1-B）

def _rules_tournament(conn, games_to_win=2, points_to_win=11):
    """创建一个 1 组 2 人的最小赛事（1 场小组赛），便于精确测试比分规则。"""
    t = repo.create_tournament(
        conn, "R", "2025-06-01", 1, 1, 1,
        games_to_win=games_to_win, points_to_win=points_to_win,
    )
    repo.create_tables_for_tournament(conn, t["id"], 1)
    repo.add_player(conn, t["id"], "A", None)
    repo.add_player(conn, t["id"], "B", None)
    groups_service.auto_group_tournament(conn, t["id"])
    matches_service.generate_group_matches(conn, t["id"])
    return t["id"]


def _only_match(conn, tid):
    return repo.list_matches(conn, tid)[0]


# 大比分（games_to_win=2）
@pytest.mark.parametrize("sa,sb", [(2, 0), (2, 1), (0, 2), (1, 2)])
def test_aggregate_valid(conn, sa, sb):
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    updated = scores_service.record_score(conn, m["id"], sa, sb)
    assert updated["status"] == "FINISHED"
    assert (updated["player_a_score"], updated["player_b_score"]) == (sa, sb)


@pytest.mark.parametrize("sa,sb", [(99, 0), (3, 0), (1, 0), (2, 2), (-1, 2)])
def test_aggregate_invalid(conn, sa, sb):
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError):
        scores_service.record_score(conn, m["id"], sa, sb)


# 单局（P=11）——黑盒：通过 record_score 提交一场完整的 2:0 比赛，逐局均为同一比分
@pytest.mark.parametrize("game", [(11, 0), (11, 9), (12, 10), (15, 13)])
def test_game_valid(conn, game):
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    updated = scores_service.record_score(conn, m["id"], None, None, games=[game, game])
    assert updated["player_a_score"] == 2
    assert updated["player_b_score"] == 0


@pytest.mark.parametrize("game", [(12, 5), (13, 9), (11, 10), (12, 11), (14, 11), (10, 10)])
def test_game_invalid(conn, game):
    # 提交两局同一非法比分：若该局被错误接受，整场本可正常达到 2 局胜利，
    # 因此此处抛错必须来自“第 1 局”的逐局校验，而不是“比赛尚未结束”。
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError) as exc_info:
        scores_service.record_score(conn, m["id"], None, None, games=[game, game])
    assert "第 1 局" in str(exc_info.value)


# 比赛级规则
def test_games_extra_after_win_rejected(conn):
    """达到 games_to_win 后仍提供多余局 → 拒绝。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError):
        scores_service.record_score(conn, m["id"], None, None, games=[(11, 5), (11, 5), (11, 5)])


def test_games_not_reaching_win_rejected(conn):
    """未达到 games_to_win → 拒绝。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError):
        scores_service.record_score(conn, m["id"], None, None, games=[(11, 5)])


# NORMAL + games 契约：aggregate 要么双方都省略、要么双方都与 games 推导完全一致
def test_games_with_omitted_aggregate_derives(conn):
    """Case A：aggregate 双方都省略 → 由 games 推导大比分。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    updated = scores_service.record_score(conn, m["id"], None, None, games=[(11, 5), (11, 5)])
    assert (updated["player_a_score"], updated["player_b_score"]) == (2, 0)


def test_games_with_matching_aggregate_accepted(conn):
    """Case B：aggregate 与 games 推导一致 → 接受。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    updated = scores_service.record_score(conn, m["id"], 2, 1, games=[(11, 8), (9, 11), (11, 6)])
    assert (updated["player_a_score"], updated["player_b_score"]) == (2, 1)


def test_games_with_opposite_winner_aggregate_rejected(conn):
    """Case C1：aggregate 胜者与 games 推导相反 → 422。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError) as exc_info:
        scores_service.record_score(conn, m["id"], 2, 0, games=[(8, 11), (9, 11)])
    assert exc_info.value.code == 422


def test_games_with_same_winner_score_mismatch_rejected(conn):
    """Case C2：胜者相同但局数不一致（2:0 vs 推导 2:1）→ 422。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError) as exc_info:
        scores_service.record_score(conn, m["id"], 2, 0, games=[(11, 8), (9, 11), (11, 6)])
    assert exc_info.value.code == 422


@pytest.mark.parametrize("sa,sb", [(2, None), (None, 0)])
def test_games_with_partial_aggregate_rejected(conn, sa, sb):
    """Case D：只提供一边 aggregate → 422。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    with pytest.raises(scores_service.ScoreError) as exc_info:
        scores_service.record_score(conn, m["id"], sa, sb, games=[(11, 5), (11, 5)])
    assert exc_info.value.code == 422


def test_revise_games_aggregate_mismatch_preserves_state(conn):
    """revise_score 与 record_score 同契约：不一致 → 422，且原状态不变。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    scores_service.record_score(conn, m["id"], None, None, games=[(11, 5), (11, 5)])
    before = repo.get_match(conn, m["id"])
    before_games = repo.list_match_games(conn, m["id"])

    with pytest.raises(scores_service.ScoreError) as exc_info:
        scores_service.revise_score(conn, m["id"], 0, 2, games=[(11, 5), (11, 5)])
    assert exc_info.value.code == 422

    after = repo.get_match(conn, m["id"])
    assert after["player_a_score"] == before["player_a_score"]
    assert after["player_b_score"] == before["player_b_score"]
    assert after["winner_id"] == before["winner_id"]
    assert repo.list_match_games(conn, m["id"]) == before_games


def test_revise_uses_same_validation(conn):
    """revise_score 与 record_score 使用同样的大比分校验。"""
    tid = _rules_tournament(conn)
    m = _only_match(conn, tid)
    scores_service.record_score(conn, m["id"], 2, 0)
    with pytest.raises(scores_service.ScoreError):
        scores_service.revise_score(conn, m["id"], 99, 0)


# ------------------------------------------------------------------ Router 层：games 缺失 vs 空数组

def _api_two_player_match(client):
    """创建 1 组 2 人的赛事并生成 1 场小组赛，返回 (tid, match_id)。"""
    resp = client.post(
        "/api/tournaments",
        json={"name": "R", "date": "2025-06-01", "table_count": 1, "group_count": 1, "qualify_per_group": 1},
    )
    tid = resp.json()["id"]
    client.post(f"/api/tournaments/{tid}/players", json={"name": "A"})
    client.post(f"/api/tournaments/{tid}/players", json={"name": "B"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    match = client.get(f"/api/tournaments/{tid}/matches").json()[0]
    return tid, match["id"]


def test_api_record_score_rejects_empty_games(client):
    """games 显式传 [] 必须被拒绝，而不是被当成未提供。"""
    _, mid = _api_two_player_match(client)
    resp = client.post(
        f"/api/matches/{mid}/score",
        json={"player_a_score": 2, "player_b_score": 0, "games": [], "result_type": "NORMAL"},
    )
    assert resp.status_code == 422


def test_api_revise_score_rejects_empty_games(client):
    """revise 同样区分 games=[] 与 games 缺失。"""
    _, mid = _api_two_player_match(client)
    client.post(f"/api/matches/{mid}/score", json={"player_a_score": 2, "player_b_score": 0})
    resp = client.post(
        f"/api/matches/{mid}/revise-score",
        json={"player_a_score": 2, "player_b_score": 0, "games": [], "result_type": "NORMAL"},
    )
    assert resp.status_code == 422


def test_api_score_without_games_field_allowed(client):
    """未提供 games 字段（games=None）时，合法大比分仍可录入。"""
    _, mid = _api_two_player_match(client)
    resp = client.post(
        f"/api/matches/{mid}/score",
        json={"player_a_score": 2, "player_b_score": 0},
    )
    assert resp.status_code == 200
    assert resp.json()["player_a_score"] == 2
    assert resp.json()["player_b_score"] == 0


def test_api_games_aggregate_mismatch_rejected(client):
    """API：games 推导（0:2）与 aggregate（2:0）不一致 → 422。"""
    _, mid = _api_two_player_match(client)
    resp = client.post(
        f"/api/matches/{mid}/score",
        json={
            "player_a_score": 2,
            "player_b_score": 0,
            "games": [
                {"side_a_score": 8, "side_b_score": 11},
                {"side_a_score": 9, "side_b_score": 11},
            ],
            "result_type": "NORMAL",
        },
    )
    assert resp.status_code == 422
