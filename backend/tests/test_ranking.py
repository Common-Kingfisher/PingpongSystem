"""排名算法测试：用固定比赛数据验证排名与晋级判定。"""

from app.domain.ranking import compute_group_rankings, compute_qualification


def _m(a, b, sa, sb, status="FINISHED"):
    """构造一场比赛记录。"""
    if sa is None or sb is None:
        winner = None
    else:
        winner = a if sa > sb else b
    return {
        "player_a_id": a,
        "player_b_id": b,
        "player_a_score": sa,
        "player_b_score": sb,
        "winner_id": winner,
        "status": status,
    }


def _gm(a, b, sa, sb, games):
    """构造一场带逐局小分的比赛。games 为 [(side_a_score, side_b_score), ...]。"""
    m = _m(a, b, sa, sb)
    m["games"] = [{"side_a_score": x, "side_b_score": y} for x, y in games]
    return m


def _gm3(a, b, loser_scores):
    """a 3:0 胜 b，逐局为 11:x（x 为 loser_scores 中对应局负方得分，均合法 11 分制）。"""
    return _gm(a, b, 3, 0, [(11, x) for x in loser_scores])


def _cycle3(l12, l23, l31):
    """3 人循环互赛：1>2、2>3、3>1，均为 3:0 且每场 3 局。l* 为各场负方 3 局得分。"""
    return [
        _gm3(1, 2, l12),   # 1 胜 2
        _gm3(2, 3, l23),   # 2 胜 3
        _gm3(3, 1, l31),   # 3 胜 1
    ]


def _round_robin_results(order_of_wins=None):
    """默认：选手 1 > 2 > 3 > 4 全部单循环 6 场。"""
    return [
        _m(1, 2, 3, 0),
        _m(1, 3, 3, 1),
        _m(1, 4, 3, 2),
        _m(2, 3, 3, 0),
        _m(2, 4, 3, 1),
        _m(3, 4, 3, 0),
    ]


def test_wins_decide_ranking():
    entries = compute_group_rankings(_round_robin_results(), [1, 2, 3, 4])
    assert [e["player_id"] for e in entries] == [1, 2, 3, 4]
    assert [e["rank"] for e in entries] == [1, 2, 3, 4]
    assert all(not e["tied"] for e in entries)
    # 胜场统计
    assert entries[0]["wins"] == 3 and entries[0]["losses"] == 0
    assert entries[1]["wins"] == 2 and entries[1]["losses"] == 1


def test_net_games_decide_when_wins_tied():
    # 1 与 2 同为 2 胜，但 1 净胜局更多 → 1 在前
    matches = [
        _m(1, 2, 3, 0),   # 1 胜
        _m(1, 3, 3, 0),   # 1 胜
        _m(1, 4, 2, 3),   # 4 胜
        _m(2, 3, 3, 0),   # 2 胜
        _m(2, 4, 3, 0),   # 2 胜
        _m(3, 4, 2, 3),   # 4 胜
    ]
    entries = compute_group_rankings(matches, [1, 2, 3, 4])
    # 胜场：1=2, 2=2, 3=0, 4=2；净胜局：1=+5, 2=+3, 4=+2, 3=-5
    assert [e["player_id"] for e in entries] == [1, 2, 4, 3]
    assert [e["rank"] for e in entries] == [1, 2, 3, 4]


def test_head_to_head_decides_two_way_tie():
    # 1 与 2 同胜场、同净胜局；1 直接交锋 3:2 胜 2 → 1 在前
    matches = [
        _m(1, 2, 3, 2),   # 1 胜（净 +1/-1）
        _m(1, 3, 3, 0),   # 1 胜（净 +3）
        _m(1, 4, 1, 3),   # 4 胜（净 -2）
        _m(2, 3, 3, 1),   # 2 胜（净 +2）
        _m(2, 4, 3, 2),   # 2 胜（净 +1）
        _m(3, 4, 3, 1),   # 3 胜（净 +2）
    ]
    entries = compute_group_rankings(matches, [1, 2, 3, 4])
    # 胜场：1=2, 2=2, 3=1, 4=1
    # 1 净胜局 = +1-2 = ... 计算：1 胜 2(3:2)+3 胜 3(3:0)=6 局，负 4(1:3) 失 3 局 → 净 +3
    # 2 胜 3(3:1)+4(3:2)=6 局，负 1(2:3) 失 3 局 → 净 +3 → 1 与 2 并列 → 交锋 1 胜 2 → 1 在前
    first_two = [e["player_id"] for e in entries[:2]]
    assert first_two == [1, 2]
    assert entries[0]["tied"] is False and entries[1]["tied"] is False


def test_three_way_tie_flagged():
    # 1,2,3 互相 1 胜 1 负（2 胜），净胜局相同 → 3 人并列，标记 tied
    matches = [
        _m(1, 2, 3, 0),   # 1 胜 2
        _m(2, 3, 3, 0),   # 2 胜 3
        _m(3, 1, 3, 0),   # 3 胜 1
        _m(1, 4, 3, 0),
        _m(2, 4, 3, 0),
        _m(3, 4, 3, 0),
    ]
    entries = compute_group_rankings(matches, [1, 2, 3, 4])
    top = entries[:3]
    assert [e["wins"] for e in top] == [2, 2, 2]
    assert all(e["tied"] for e in top)
    assert len({e["rank"] for e in top}) == 1  # 同 rank
    assert entries[3]["player_id"] == 4 and entries[3]["rank"] == 4


def test_partial_group_ranking_uses_finished_only():
    # 只有 1 胜 2 一场完成 → 1 有 1 胜，其余 0 胜
    matches = [
        _m(1, 2, 3, 1),
        _m(1, 3, None, None, status="WAITING"),
        _m(2, 3, None, None, status="WAITING"),
    ]
    entries = compute_group_rankings(matches, [1, 2, 3])
    by_id = {e["player_id"]: e for e in entries}
    assert by_id[1]["wins"] == 1
    assert by_id[2]["wins"] == 0
    assert by_id[3]["wins"] == 0
    assert entries[0]["player_id"] == 1


def test_qualification_clear_top2():
    entries = compute_group_rankings(_round_robin_results(), [1, 2, 3, 4])
    qualified, ambiguous = compute_qualification(entries, 2)
    assert ambiguous is False
    assert qualified == [1, 2]


def test_qualification_tie_at_cutoff_ambiguous():
    matches = [
        _m(1, 2, 3, 0), _m(2, 3, 3, 0), _m(3, 1, 3, 0),
        _m(1, 4, 3, 0), _m(2, 4, 3, 0), _m(3, 4, 3, 0),
    ]
    entries = compute_group_rankings(matches, [1, 2, 3, 4])
    qualified, ambiguous = compute_qualification(entries, 2)
    assert ambiguous is True
    assert qualified == []  # 不编造晋级者


# ------------------------------------------------------------------ R04-A：多人同分 partial resolution

def test_partial_ties_all_resolved():
    """CASE A：三人 ratio 全不同（1.167 / 0.929 / 0.923）→ 全部独立排名。"""
    matches = _cycle3([1, 1, 1], [2, 2, 2], [3, 3, 3])
    entries = compute_group_rankings(matches, [1, 2, 3])
    assert [e["player_id"] for e in entries] == [1, 3, 2]
    assert [e["rank"] for e in entries] == [1, 2, 3]
    assert all(not e["tied"] for e in entries)


def test_partial_ties_last_two_tied():
    """CASE B：1 > 2 = 3（ratio 1.361 / 0.857 / 0.857）→ 1 独立，2/3 并列。"""
    matches = _cycle3([1, 1, 1], [3, 3, 3], [5, 5, 6])
    entries = compute_group_rankings(matches, [1, 2, 3])
    by_id = {e["player_id"]: e for e in entries}
    assert by_id[1]["rank"] == 1 and by_id[1]["tied"] is False
    assert by_id[2]["rank"] == 2 and by_id[2]["tied"] is True
    assert by_id[3]["rank"] == 2 and by_id[3]["tied"] is True


def test_partial_ties_first_two_tied():
    """CASE C：1 = 2 > 3（ratio 1.167 / 1.167 / 0.735）→ 1/2 并列 rank1，3 独立 rank3。"""
    matches = _cycle3([3, 3, 3], [1, 1, 1], [5, 5, 6])
    entries = compute_group_rankings(matches, [1, 2, 3])
    by_id = {e["player_id"]: e for e in entries}
    assert by_id[1]["rank"] == 1 and by_id[1]["tied"] is True
    assert by_id[2]["rank"] == 1 and by_id[2]["tied"] is True
    assert by_id[3]["rank"] == 3 and by_id[3]["tied"] is False


def test_partial_ties_all_equal_keep_tied():
    """CASE D：三人 ratio 全相同 → 保持整桶并列。"""
    matches = _cycle3([1, 1, 1], [1, 1, 1], [1, 1, 1])
    entries = compute_group_rankings(matches, [1, 2, 3])
    assert all(e["tied"] for e in entries)
    assert len({e["rank"] for e in entries}) == 1


def test_partial_ties_missing_games_keeps_unresolved():
    """CASE E：缺相关逐局小分 → 不得按 0 分，保持 unresolved。"""
    matches = [
        _gm3(1, 2, [1, 1, 1]),
        _m(2, 3, 3, 0),   # 无 games
        _gm3(3, 1, [3, 3, 3]),
    ]
    entries = compute_group_rankings(matches, [1, 2, 3])
    assert all(e["tied"] for e in entries)
    assert len({e["rank"] for e in entries}) == 1


def test_partial_ties_qualification_not_blocked_by_irrelevant_tie():
    """CASE F：1 > 2 = 3；qualify=1 时 1 明确晋级，不被无关的 2/3 并列阻止。"""
    matches = _cycle3([1, 1, 1], [3, 3, 3], [5, 5, 6])
    entries = compute_group_rankings(matches, [1, 2, 3])
    qualified, ambiguous = compute_qualification(entries, 1)
    assert ambiguous is False
    assert qualified == [1]


def test_partial_ties_qualification_ambiguous_at_cutoff():
    """CASE F 反向：1 > 2 = 3；qualify=2 时 2/3 并列跨越晋级线 → ambiguous。"""
    matches = _cycle3([1, 1, 1], [3, 3, 3], [5, 5, 6])
    entries = compute_group_rankings(matches, [1, 2, 3])
    qualified, ambiguous = compute_qualification(entries, 2)
    assert ambiguous is True
    assert qualified == [1]  # 1 明确晋级；不任意选择 2 或 3


def test_qualification_whole_tied_group_within_cutoff():
    """CASE G：rank 1,2,2 / qualify=3 → 三人全部晋级，不 ambiguous。"""
    matches = _cycle3([1, 1, 1], [3, 3, 3], [5, 5, 6])
    entries = compute_group_rankings(matches, [1, 2, 3])
    qualified, ambiguous = compute_qualification(entries, 3)
    assert ambiguous is False
    assert sorted(qualified) == [1, 2, 3]


def test_qualification_tied_group_fully_inside_cutoff():
    """CASE H：rank 1,1,3 / qualify=2 → 两名 rank1 全部晋级，不 ambiguous。"""
    matches = _cycle3([3, 3, 3], [1, 1, 1], [5, 5, 6])
    entries = compute_group_rankings(matches, [1, 2, 3])
    qualified, ambiguous = compute_qualification(entries, 2)
    assert ambiguous is False
    assert sorted(qualified) == [1, 2]
