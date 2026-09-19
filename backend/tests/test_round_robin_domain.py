"""单循环编排算法（`domain/round_robin.py`）的通用不变量测试（A6.1 补充）。

A6.1 的"团体小组循环生成"直接复用这份个人赛算法（没有为 TEAM 复制第二份），
所以这里把"任何 n 都必须成立"的性质锁死，小 n 尤其重要：

- 场数 = n×(n-1)/2；
- 每个 unordered pair **恰好出现一次**，绝不出现 a vs a；
- 每支队伍每轮最多出场一次；
- 轮数：偶数 n → n-1 轮，每轮 n/2 场；奇数 n → n 轮，每轮 (n-1)/2 场 + 1 支轮空；
- 轮空**不产生对局**（不制造 `<队伍> vs NULL` 这种假对阵）；
- 多次运行结果完全一致（确定性、无随机）。

算法本身是纯函数：输入是"有稳定顺序的 id 列表"，输出 `[(round, a, b), ...]`，round 从 1 开始。
"""

import itertools

import pytest

from app.domain.round_robin import round_robin

N_VALUES = (2, 3, 4, 5, 6, 7, 8, 11, 12)


def _pairs(schedule):
    return [frozenset((a, b)) for _, a, b in schedule]


def _grouped_by_round(schedule):
    by_round: dict[int, list[tuple[int, int]]] = {}
    for round_num, a, b in schedule:
        by_round.setdefault(round_num, []).append((a, b))
    return by_round


# ------------------------------------------------------------------ 各 n 的具体行为

def test_two_teams_one_tie():
    schedule = round_robin([1, 2])
    assert schedule == [(1, 1, 2)]


def test_three_teams_three_ties_one_bye_each_round():
    schedule = round_robin([1, 2, 3])
    assert len(schedule) == 3
    assert {frozenset((a, b)) for _, a, b in schedule} == {
        frozenset(p) for p in itertools.combinations([1, 2, 3], 2)
    }
    by_round = _grouped_by_round(schedule)
    assert sorted(by_round) == [1, 2, 3]
    # 3 队 = 3 轮 × 1 场，每轮恰好 1 支队伍轮空（轮空不落库，只体现为"这场没有它"）
    appearances: dict[int, int] = {1: 0, 2: 0, 3: 0}
    for plays in by_round.values():
        assert len(plays) == 1
        assert plays[0][0] != plays[0][1]
        for a, b in plays:
            appearances[a] += 1
            appearances[b] += 1
    assert appearances == {1: 2, 2: 2, 3: 2}  # 每队 2 场 = n-1


def test_four_teams_six_ties_three_rounds_two_per_round():
    schedule = round_robin([1, 2, 3, 4])
    assert len(schedule) == 6  # 4×3/2
    assert {frozenset((a, b)) for _, a, b in schedule} == {
        frozenset(p) for p in itertools.combinations([1, 2, 3, 4], 2)
    }
    by_round = _grouped_by_round(schedule)
    assert sorted(by_round) == [1, 2, 3]
    assert all(len(plays) == 2 for plays in by_round.values())
    # 每队 3 场
    counts: dict[int, int] = {i: 0 for i in range(1, 5)}
    for _, a, b in schedule:
        counts[a] += 1
        counts[b] += 1
    assert counts == {1: 3, 2: 3, 3: 3, 4: 3}


def test_five_teams_ten_ties_five_rounds_with_bye():
    schedule = round_robin([1, 2, 3, 4, 5])
    assert len(schedule) == 10  # 5×4/2
    by_round = _grouped_by_round(schedule)
    assert sorted(by_round) == [1, 2, 3, 4, 5]
    # 5 队：每轮 2 场 + 1 队轮空
    assert all(len(plays) == 2 for plays in by_round.values())
    appearances: dict[int, int] = {i: 0 for i in range(1, 6)}
    for _, a, b in schedule:
        appearances[a] += 1
        appearances[b] += 1
    assert appearances == {i: 4 for i in range(1, 6)}  # 每队 4 场 = n-1
    # 轮空恰好一次：每轮恰有一队不出场
    byes_per_round = [
        {i for i in range(1, 6)} - {x for play in plays for x in play}
        for plays in by_round.values()
    ]
    assert all(len(byes) == 1 for byes in byes_per_round)
    assert sorted(bye for byes in byes_per_round for bye in byes) == [1, 2, 3, 4, 5]


def test_six_teams_fifteen_ties_five_rounds_three_per_round():
    schedule = round_robin([1, 2, 3, 4, 5, 6])
    assert len(schedule) == 15  # 6×5/2
    by_round = _grouped_by_round(schedule)
    assert sorted(by_round) == [1, 2, 3, 4, 5]
    assert all(len(plays) == 3 for plays in by_round.values())
    appearances: dict[int, int] = {i: 0 for i in range(1, 7)}
    for _, a, b in schedule:
        appearances[a] += 1
        appearances[b] += 1
    assert appearances == {i: 5 for i in range(1, 7)}  # 每队 5 场 = n-1


# ------------------------------------------------------------------ 通用不变量（多 n）

@pytest.mark.parametrize("n", N_VALUES)
def test_tie_count_is_n_choose_2(n):
    ids = list(range(1, n + 1))
    schedule = round_robin(ids)
    assert len(schedule) == n * (n - 1) // 2


@pytest.mark.parametrize("n", N_VALUES)
def test_every_unordered_pair_exactly_once(n):
    ids = list(range(1, n + 1))
    schedule = round_robin(ids)
    pairs = _pairs(schedule)
    assert len(pairs) == len(set(pairs)), "出现重复对阵"
    assert set(pairs) == {frozenset(p) for p in itertools.combinations(ids, 2)}


@pytest.mark.parametrize("n", N_VALUES)
def test_no_self_match(n):
    schedule = round_robin(list(range(1, n + 1)))
    assert all(a != b for _, a, b in schedule)


@pytest.mark.parametrize("n", N_VALUES)
def test_each_team_at_most_once_per_round(n):
    ids = list(range(1, n + 1))
    schedule = round_robin(ids)
    for round_num, plays in _grouped_by_round(schedule).items():
        appeared = [x for play in plays for x in play]
        assert len(appeared) == len(set(appeared)), f"第 {round_num} 轮有人出场两次"


@pytest.mark.parametrize("n", N_VALUES)
def test_round_structure_matches_parity(n):
    ids = list(range(1, n + 1))
    by_round = _grouped_by_round(round_robin(ids))
    assert sorted(by_round) == list(range(1, (n if n % 2 else n - 1) + 1))
    expected_per_round = n // 2 if n % 2 == 0 else (n - 1) // 2
    assert all(len(plays) == expected_per_round for plays in by_round.values())


@pytest.mark.parametrize("n", N_VALUES)
def test_each_team_plays_n_minus_1(n):
    ids = list(range(1, n + 1))
    schedule = round_robin(ids)
    appearances = {i: 0 for i in ids}
    for _, a, b in schedule:
        appearances[a] += 1
        appearances[b] += 1
    assert appearances == {i: n - 1 for i in ids}


@pytest.mark.parametrize("n", (3, 5, 7, 11))
def test_odd_team_count_has_exactly_one_bye_per_round(n):
    ids = list(range(1, n + 1))
    for round_num, plays in _grouped_by_round(round_robin(ids)).items():
        resting = set(ids) - {x for play in plays for x in play}
        assert len(resting) == 1, f"n={n} 第 {round_num} 轮轮空队伍数不是 1"


@pytest.mark.parametrize("n", N_VALUES)
def test_schedule_is_deterministic(n):
    ids = list(range(1, n + 1))
    assert round_robin(ids) == round_robin(ids) == round_robin(list(ids))


def test_input_order_drives_output_order_only_by_values():
    """不同 id 取值但同样的相对顺序 → 同样的**结构**（算法不依赖 id 大小或随机数）。"""
    a = round_robin([10, 20, 30, 40])
    b = round_robin([1, 2, 3, 4])
    assert len(a) == len(b)
    assert [r for r, _, _ in a] == [r for r, _, _ in b]
    # 每个 id 在 (round, slot) 上的位置与另一份完全对应
    mapping = {10: 1, 20: 2, 30: 3, 40: 4}
    assert [(r, mapping[x], mapping[y]) for r, x, y in a] == b


def test_too_few_teams_produce_no_ties():
    assert round_robin([]) == []
    assert round_robin([5]) == []
    assert round_robin([]) == round_robin([5])
