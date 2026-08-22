"""轮转法单循环算法测试。

核心性质（对任意人数成立）：
- 场数 = n×(n-1)/2
- 每对选手恰好一次、无自己 vs 自己
- 每名选手恰好出场 n-1 次
- 同一轮内每名选手至多出场一次
"""

import itertools
from collections import Counter

from app.domain.round_robin import round_robin


def _pair_set(schedule):
    return {frozenset((a, b)) for _, a, b in schedule}


def _all_combinations(ids):
    return {frozenset(p) for p in itertools.combinations(ids, 2)}


def test_six_players_exactly_fifteen_matches():
    ids = [1, 2, 3, 4, 5, 6]
    schedule = round_robin(ids)
    assert len(schedule) == 15  # 6×5/2
    assert _pair_set(schedule) == _all_combinations(ids)
    assert all(a != b for _, a, b in schedule)


def test_five_players_ten_matches_with_bye():
    ids = [1, 2, 3, 4, 5]
    schedule = round_robin(ids)
    assert len(schedule) == 10  # 5×4/2
    assert _pair_set(schedule) == _all_combinations(ids)


def test_two_players_one_match():
    schedule = round_robin([7, 8])
    assert schedule == [(1, 7, 8)]


def test_three_players_three_matches():
    ids = [1, 2, 3]
    schedule = round_robin(ids)
    assert len(schedule) == 3
    assert _pair_set(schedule) == _all_combinations(ids)


def test_one_player_no_matches():
    assert round_robin([1]) == []


def test_zero_players_no_matches():
    assert round_robin([]) == []


def test_eight_players_seven_rounds_each_4_matches():
    ids = list(range(1, 9))
    schedule = round_robin(ids)
    assert len(schedule) == 28  # 8×7/2
    rounds = Counter(r for r, _, _ in schedule)
    assert set(rounds.keys()) == set(range(1, 8))  # 7 轮
    assert all(count == 4 for count in rounds.values())


def test_each_player_plays_n_minus_1():
    ids = list(range(1, 7))
    schedule = round_robin(ids)
    appearances = Counter()
    for _, a, b in schedule:
        appearances[a] += 1
        appearances[b] += 1
    assert all(appearances[i] == 5 for i in ids)


def test_no_player_twice_in_same_round():
    ids = list(range(1, 7))
    schedule = round_robin(ids)
    by_round: dict[int, list[int]] = {}
    for r, a, b in schedule:
        by_round.setdefault(r, []).extend([a, b])
    for players in by_round.values():
        assert len(players) == len(set(players))
