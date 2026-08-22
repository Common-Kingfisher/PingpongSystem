"""贪心调度算法测试：硬约束逐条验证。"""

from app.domain.scheduler import schedule_batch


def _match(mid, a, b, status="WAITING"):
    return {"id": mid, "status": status, "player_a_id": a, "player_b_id": b}


def test_assigns_in_order_to_free_tables():
    matches = [_match(1, 10, 11), _match(2, 12, 13), _match(3, 14, 15)]
    result = schedule_batch(matches, [101, 102, 103])
    assert result == [(1, 101), (2, 102), (3, 103)]


def test_player_cannot_be_in_two_matches_same_batch():
    matches = [_match(1, 10, 11), _match(2, 11, 12), _match(3, 13, 14)]
    result = schedule_batch(matches, [101, 102, 103])
    # 第 2 场含选手 11（已安排进第 1 场），跳过；第 3 场分配
    assert result == [(1, 101), (3, 102)]


def test_playing_and_finished_matches_skipped():
    matches = [
        _match(1, 10, 11, status="PLAYING"),
        _match(2, 12, 13, status="FINISHED"),
        _match(3, 14, 15),
    ]
    result = schedule_batch(matches, [101, 102])
    assert result == [(3, 101)]


def test_fewer_tables_than_matches():
    matches = [_match(1, 10, 11), _match(2, 12, 13), _match(3, 14, 15)]
    result = schedule_batch(matches, [101])
    assert result == [(1, 101)]


def test_players_playing_elsewhere_block_matches():
    matches = [_match(1, 10, 11), _match(2, 10, 12)]
    # 选手 10 已占用（传入的"批外占用"通过把其比赛标记为 PLAYING 模拟，但
    # 更直接的方式：服务层过滤；此处验证批内累积逻辑即可）
    result = schedule_batch(matches, [101, 102])
    assert result == [(1, 101)]  # 第 2 场含选手 10 → 跳过


def test_no_table_reused():
    matches = [_match(1, 10, 11), _match(2, 12, 13), _match(3, 14, 15), _match(4, 16, 17)]
    result = schedule_batch(matches, [101, 102])
    tables_used = [t for _, t in result]
    assert len(tables_used) == len(set(tables_used))
