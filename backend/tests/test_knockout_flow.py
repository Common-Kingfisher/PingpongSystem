"""淘汰赛全流程测试：晋级、胜者晋级、输家不复活、改分级联重置、唯一冠军。"""

import pytest

from app import repository as repo
from app.services import groups as groups_service
from app.services import knockout as knockout_service
from app.services import matches as matches_service
from app.services import rankings as rankings_service
from app.services import scheduling as scheduling_service
from app.services import scores as scores_service
from app.models import MatchStatus, TournamentStage


def _build_tournament(conn, n_players=8, group_count=4, qualify=2, table_count=6):
    t = repo.create_tournament(conn, "T", "2025-06-01", table_count, group_count, qualify)
    repo.create_tables_for_tournament(conn, t["id"], table_count)
    for i in range(1, n_players + 1):
        repo.add_player(conn, t["id"], f"P{i}", None)
    groups_service.auto_group_tournament(conn, t["id"])
    matches_service.generate_group_matches(conn, t["id"])
    return t["id"]


def _score_playing_matches(conn, tid):
    """把所有 PLAYING 比赛按"id 小者 2:0 胜"录分。"""
    for m in repo.list_playing_matches(conn, tid):
        w = min(m["player_a_id"], m["player_b_id"])
        sa, sb = (2, 0) if w == m["player_a_id"] else (0, 2)
        scores_service.record_score(conn, m["id"], sa, sb)


def _play_all(conn, tid):
    """批量调度 + 录分，直到全部比赛结束。"""
    for _ in range(200):
        assignments = scheduling_service.schedule_next(conn, tid)
        playing = repo.list_playing_matches(conn, tid)
        if not assignments and not playing:
            return
        _score_playing_matches(conn, tid)


def _assert_losers_never_reappear(conn, tid):
    """单败淘汰不变量：
    1. 每个轮次内每名选手至多出现一次；
    2. 输家不会出现在其输掉比赛之后的任何轮次。
    """
    matches = repo.list_matches(conn, tid, stage="KNOCKOUT")
    per_round: dict[int, set[int]] = {}
    for m in matches:
        for pid in (m["player_a_id"], m["player_b_id"]):
            if pid is None:
                continue
            seen = per_round.setdefault(m["round"], set())
            assert pid not in seen, f"选手 {pid} 在同一轮出现多次"
            seen.add(pid)

    loss_round: dict[int, int] = {}
    for m in matches:
        if m["status"] == MatchStatus.FINISHED.value and m["winner_id"] is not None:
            loser = (
                m["player_b_id"] if m["winner_id"] == m["player_a_id"] else m["player_a_id"]
            )
            loss_round[loser] = m["round"]
    for pid, round_lost in loss_round.items():
        for m in matches:
            if m["round"] > round_lost and pid in (m["player_a_id"], m["player_b_id"]):
                raise AssertionError(f"输家 {pid} 出现在第 {m['round']} 轮（第 {round_lost} 轮已输）")


# ------------------------------------------------------------ 全流程

def test_quarterfinal_entry_pairing_follows_head_to_tail_cross(conn):
    """4 组 × 每组前 2：八强实际 entry 配对必须是 A1-D2 / C1-B2 / B1-C2 / D1-A2。"""
    tid = _build_tournament(conn, n_players=16, group_count=4, qualify=2)
    _play_all(conn, tid)

    rankings = rankings_service.get_rankings(conn, tid)
    label_of: dict[int, tuple[str, int]] = {}
    for group in rankings:
        rank = 0
        for entry in group["entries"]:
            if entry["qualified"]:
                rank += 1
                label_of[entry["player_id"]] = (group["group_name"], rank)

    knockout_service.generate_knockout(conn, tid)
    first_round = [
        match
        for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["bracket"] == "MAIN" and match["round"] == 1
    ]

    pairs = {
        frozenset((label_of[match["entry_a_id"]], label_of[match["entry_b_id"]]))
        for match in first_round
    }
    assert pairs == {
        frozenset({("A组", 1), ("D组", 2)}),
        frozenset({("C组", 1), ("B组", 2)}),
        frozenset({("B组", 1), ("C组", 2)}),
        frozenset({("D组", 1), ("A组", 2)}),
    }
    # 同组两人不在首轮相遇
    for match in first_round:
        group_a = label_of[match["entry_a_id"]][0]
        group_b = label_of[match["entry_b_id"]][0]
        assert group_a != group_b


def test_full_flow_to_unique_champion(conn):
    tid = _build_tournament(conn)  # 8 人 / 4 组 × 2
    _play_all(conn, tid)

    rankings = rankings_service.get_rankings(conn, tid)
    assert all(g["finished_matches"] == g["total_matches"] for g in rankings)

    tree = knockout_service.generate_knockout(conn, tid)
    rounds = tree["rounds"]
    assert [len(r["matches"]) for r in rounds] == [4, 2, 1]
    assert [r["label"] for r in rounds] == ["8强赛", "半决赛", "决赛"]

    # 首轮：全部晋级者恰好各出场一次（不重不漏）
    qualified = {e["player_id"] for g in rankings for e in g["entries"] if e["qualified"]}
    first_players = [
        pid for m in rounds[0]["matches"] for pid in (m["player_a"]["id"], m["player_b"]["id"])
    ]
    assert sorted(first_players) == sorted(qualified)
    assert len(first_players) == len(set(first_players))

    # 打完淘汰赛 → 唯一冠军（id 最小者全胜）
    _play_all(conn, tid)
    tree2 = knockout_service.get_knockout(conn, tid)
    assert tree2["champion"]["id"] == 1
    assert tree2["runner_up"] is not None
    assert tree2["runner_up"]["id"] != 1
    assert repo.get_tournament(conn, tid)["stage"] == TournamentStage.FINISHED.value
    _assert_losers_never_reappear(conn, tid)


def test_winner_advances_to_next_round(conn):
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)

    qf1 = next(
        m for m in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if m["round"] == 1 and m["match_index"] == 0
    )
    table = next(t for t in repo.list_tables(conn, tid) if t["status"] == "FREE")
    scheduling_service.assign_table(conn, qf1["id"], table["id"])
    w = min(qf1["player_a_id"], qf1["player_b_id"])
    sa, sb = (2, 0) if w == qf1["player_a_id"] else (0, 2)
    scores_service.record_score(conn, qf1["id"], sa, sb)

    # 下一轮对应比赛（引用 qf1 的槽位）应填入胜者
    nxt = repo.list_matches_by_prev(conn, qf1["id"])
    assert len(nxt) == 1
    assert w in (nxt[0]["player_a_id"], nxt[0]["player_b_id"])
    # 另一场半决赛槽位仍为空
    sf = repo.get_match(conn, nxt[0]["id"])
    other_slot = sf["player_a_id"] if sf["prev_match_a_id"] != qf1["id"] else sf["player_b_id"]
    assert other_slot is None


# ------------------------------------------------------------ 守卫

def test_generate_before_groups_finished(conn):
    tid = _build_tournament(conn)
    # 小组赛一场未打 → 拒绝生成
    try:
        knockout_service.generate_knockout(conn, tid)
        assert False, "小组未结束应拒绝生成"
    except knockout_service.KnockoutError as exc:
        assert "尚未全部结束" in str(exc)


def test_generate_with_ambiguous_qualification(conn):
    # 2 组 × 4 人；第二组制造 2/3/4 名循环并列（晋级线 2 名处歧义）
    tid = _build_tournament(conn, n_players=8, group_count=2, qualify=2)
    groups = repo.list_groups(conn, tid)
    for group in groups:
        members = sorted(
            p["id"] for p in repo.list_players(conn, tid) if p["group_id"] == group["id"]
        )
        x = members[0]
        o0, o1, o2 = members[1:]
        for m in repo.list_matches(conn, tid, group_id=group["id"]):
            a, b = m["player_a_id"], m["player_b_id"]
            if x in (a, b):
                sa, sb = (2, 0) if a == x else (0, 2)
            else:
                pair = {a, b}
                if pair == {o0, o1}:
                    winner = o0
                elif pair == {o1, o2}:
                    winner = o1
                else:
                    winner = o2  # {o0, o2}
                sa, sb = (2, 1) if winner == a else (1, 2)
            repo.update_match(conn, m["id"], status="PLAYING")
            scores_service.record_score(conn, m["id"], sa, sb)
    try:
        knockout_service.generate_knockout(conn, tid)
        assert False, "并列歧义应拒绝生成"
    except knockout_service.KnockoutError as exc:
        assert "并列" in str(exc)


def test_generate_twice_rejected(conn):
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    try:
        knockout_service.generate_knockout(conn, tid)
        assert False, "重复生成应拒绝"
    except knockout_service.KnockoutError:
        pass


# ------------------------------------------------------------ 改分级联重置

def _finish_knockout(conn, tid):
    _play_all(conn, tid)
    assert repo.get_tournament(conn, tid)["stage"] == TournamentStage.FINISHED.value


def test_revise_semi_final_blocked_when_final_finished(conn):
    """决赛已结束后，修改半决赛应被阻止（结果已影响后续比赛）。"""
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    _finish_knockout(conn, tid)

    sfs = [m for m in repo.list_matches(conn, tid, stage="KNOCKOUT") if m["round"] == 2]
    champion = knockout_service.get_knockout(conn, tid)["champion"]["id"]
    sf = next(m for m in sfs if champion in (m["player_a_id"], m["player_b_id"]))
    new_sa, new_sb = (1, 2) if champion == sf["player_a_id"] else (2, 1)
    try:
        scores_service.revise_score(conn, sf["id"], new_sa, new_sb)
        assert False, "决赛已结束，应阻止修改半决赛"
    except scores_service.ScoreError as exc:
        assert "影响后续比赛" in str(exc)

    final = next(m for m in repo.list_matches(conn, tid, stage="KNOCKOUT") if m["round"] == 3)
    assert final["status"] == MatchStatus.FINISHED.value  # 决赛结果未被破坏


def test_revise_quarter_final_blocked_when_sf_played(conn):
    """半决赛已结束后，修改八强应被阻止。"""
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    _finish_knockout(conn, tid)

    qf1 = next(
        m for m in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if m["round"] == 1 and m["match_index"] == 0
    )
    w = min(qf1["player_a_id"], qf1["player_b_id"])
    new_sa, new_sb = (1, 2) if w == qf1["player_a_id"] else (2, 1)
    try:
        scores_service.revise_score(conn, qf1["id"], new_sa, new_sb)
        assert False, "半决赛已结束，应阻止修改八强"
    except scores_service.ScoreError as exc:
        assert "影响后续比赛" in str(exc)


def test_revise_quarter_final_allowed_before_sf_played(conn):
    """半决赛尚未开始时，允许修改八强，旧胜者移出、新胜者填入半决赛槽位。"""
    tid = _build_tournament(conn)
    _play_all(conn, tid)  # 只打完小组赛
    knockout_service.generate_knockout(conn, tid)

    qfs = sorted(
        (m for m in repo.list_matches(conn, tid, stage="KNOCKOUT") if m["round"] == 1),
        key=lambda m: m["match_index"],
    )
    # 打完 QF1、QF2（SF1 双方就绪但未开始）
    for qf in qfs[:2]:
        table = next(t for t in repo.list_tables(conn, tid) if t["status"] == "FREE")
        scheduling_service.assign_table(conn, qf["id"], table["id"])
        w = min(qf["player_a_id"], qf["player_b_id"])
        sa, sb = (2, 0) if w == qf["player_a_id"] else (0, 2)
        scores_service.record_score(conn, qf["id"], sa, sb)

    qf1 = qfs[0]
    old_winner = repo.get_match(conn, qf1["id"])["winner_id"]
    new_winner = qf1["player_b_id"] if old_winner == qf1["player_a_id"] else qf1["player_a_id"]
    new_sa, new_sb = (1, 2) if old_winner == qf1["player_a_id"] else (2, 1)
    scores_service.revise_score(conn, qf1["id"], new_sa, new_sb)

    sf1 = repo.list_matches_by_prev(conn, qf1["id"])[0]
    assert new_winner in (sf1["player_a_id"], sf1["player_b_id"])
    assert old_winner not in (sf1["player_a_id"], sf1["player_b_id"])
    assert sf1["status"] == MatchStatus.WAITING.value


def test_revise_quarter_final_without_winner_change_preserves_playing_semifinal(conn):
    """仅改局分时，下游参赛者未变，已开打的半决赛不得被重置或阻断。"""
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)

    qfs = sorted(
        (m for m in repo.list_matches(conn, tid, stage="KNOCKOUT") if m["round"] == 1),
        key=lambda m: m["match_index"],
    )
    for qf in qfs[:2]:
        scores_service.record_score(conn, qf["id"], 2, 0)

    qf1 = repo.get_match(conn, qfs[0]["id"])
    semifinal = repo.list_matches_by_prev(conn, qf1["id"])[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, semifinal["id"], table["id"])
    before = repo.get_match(conn, semifinal["id"])

    updated = scores_service.revise_score(conn, qf1["id"], 2, 1)

    assert (updated["player_a_score"], updated["player_b_score"]) == (2, 1)
    after = repo.get_match(conn, semifinal["id"])
    assert after["status"] == MatchStatus.PLAYING.value
    assert after["table_id"] == before["table_id"]
    assert (after["player_a_id"], after["player_b_id"]) == (
        before["player_a_id"],
        before["player_b_id"],
    )


def test_revise_quarter_final_winner_change_is_atomic_when_semifinal_playing(conn):
    """胜者反转会换下游参赛者时，已开打半决赛必须阻止且不留下半写入。"""
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)

    qfs = sorted(
        (m for m in repo.list_matches(conn, tid, stage="KNOCKOUT") if m["round"] == 1),
        key=lambda m: m["match_index"],
    )
    for qf in qfs[:2]:
        scores_service.record_score(conn, qf["id"], 2, 0)

    qf1 = repo.get_match(conn, qfs[0]["id"])
    semifinal = repo.list_matches_by_prev(conn, qf1["id"])[0]
    table = repo.list_tables(conn, tid)[0]
    scheduling_service.assign_table(conn, semifinal["id"], table["id"])
    before_upstream = repo.get_match(conn, qf1["id"])
    before_downstream = repo.get_match(conn, semifinal["id"])

    with pytest.raises(scores_service.ScoreError, match="影响后续比赛"):
        scores_service.revise_score(conn, qf1["id"], 0, 2)

    after_upstream = repo.get_match(conn, qf1["id"])
    after_downstream = repo.get_match(conn, semifinal["id"])
    assert (after_upstream["player_a_score"], after_upstream["player_b_score"]) == (
        before_upstream["player_a_score"],
        before_upstream["player_b_score"],
    )
    assert (after_downstream["player_a_id"], after_downstream["player_b_id"]) == (
        before_downstream["player_a_id"],
        before_downstream["player_b_id"],
    )
    assert after_downstream["status"] == MatchStatus.PLAYING.value


def test_revise_quarter_final_winner_change_is_atomic_when_final_finished(conn):
    """胜者反转影响已完成决赛时，上下游事实都必须原样保留。"""
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    _finish_knockout(conn, tid)

    qf = next(
        match
        for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["round"] == 1 and match["match_index"] == 0
    )
    final = next(
        match
        for match in repo.list_matches(conn, tid, stage="KNOCKOUT")
        if match["round"] == 3
    )
    before_upstream = repo.get_match(conn, qf["id"])
    before_final = repo.get_match(conn, final["id"])
    reversed_score = (
        (0, 2)
        if before_upstream["player_a_score"] > before_upstream["player_b_score"]
        else (2, 0)
    )

    with pytest.raises(scores_service.ScoreError, match="影响后续比赛"):
        scores_service.revise_score(conn, qf["id"], *reversed_score)

    after_upstream = repo.get_match(conn, qf["id"])
    after_final = repo.get_match(conn, final["id"])
    assert (after_upstream["player_a_score"], after_upstream["player_b_score"]) == (
        before_upstream["player_a_score"],
        before_upstream["player_b_score"],
    )
    assert (after_final["player_a_id"], after_final["player_b_id"]) == (
        before_final["player_a_id"],
        before_final["player_b_id"],
    )
    assert after_final["status"] == MatchStatus.FINISHED.value


def test_revise_final_flips_champion(conn):
    tid = _build_tournament(conn)
    _play_all(conn, tid)
    knockout_service.generate_knockout(conn, tid)
    _finish_knockout(conn, tid)

    final = next(m for m in repo.list_matches(conn, tid, stage="KNOCKOUT") if m["round"] == 3)
    champion = min(final["player_a_id"], final["player_b_id"])
    other = max(final["player_a_id"], final["player_b_id"])
    if champion == final["player_a_id"]:
        new_sa, new_sb = 1, 2
    else:
        new_sa, new_sb = 2, 1
    scores_service.revise_score(conn, final["id"], new_sa, new_sb)

    tree = knockout_service.get_knockout(conn, tid)
    assert tree["champion"]["id"] == other
    assert tree["runner_up"]["id"] == champion
    # 决赛改分仍是决赛结果 → 赛事保持 FINISHED
    assert repo.get_tournament(conn, tid)["stage"] == TournamentStage.FINISHED.value
