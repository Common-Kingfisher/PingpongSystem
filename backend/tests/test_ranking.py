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
