"""淘汰赛 bracket 算法测试：对阵结构、无重复、prev 追溯、范围限制。"""

import pytest

from app.domain.knockout import build_bracket


def _groups(ids_by_group):
    """[[g1_1, g1_2], [g2_1, g2_2], ...]"""
    return [list(g) for g in ids_by_group]


def _first_round_pairs(qualifiers, **kwargs):
    rounds_spec = build_bracket(_groups(qualifiers), **kwargs)
    return [(m["player_a_id"], m["player_b_id"]) for m in rounds_spec[0]]


def test_4_groups_cross_pairing():
    """已冻结规则：QF1=A1-D2、QF2=C1-B2、QF3=B1-C2、QF4=D1-A2。"""
    pairs = _first_round_pairs([[11, 12], [21, 22], [31, 32], [41, 42]])
    assert pairs == [(11, 42), (31, 22), (21, 32), (41, 12)]


@pytest.mark.parametrize("group_count", [2, 4, 8])
def test_even_groups_use_head_to_tail_cross(group_count):
    """偶数组（无轮空）：第 i 组第 1 名 ⇄ 倒数第 i 组第 2 名。"""
    groups = [[index * 10 + 1, index * 10 + 2] for index in range(1, group_count + 1)]

    pairs = _first_round_pairs(groups)

    assert all(a is not None and b is not None for a, b in pairs)
    expected = {
        frozenset((groups[index][0], groups[group_count - 1 - index][1]))
        for index in range(group_count)
    }
    assert {frozenset(pair) for pair in pairs} == expected


@pytest.mark.parametrize("group_count", [2, 4, 8])
def test_group_mates_and_top_seeds_in_opposite_halves(group_count):
    """同组两人与 1/2 号种子分处不同半区（最早决赛相遇）。"""
    groups = [[index * 10 + 1, index * 10 + 2] for index in range(1, group_count + 1)]

    pairs = _first_round_pairs(groups)
    half = len(pairs) // 2
    upper = {pid for pair in pairs[:half] for pid in pair}
    lower = {pid for pair in pairs[half:] for pid in pair}

    for group in groups:
        for player_id in group:
            assert (player_id in upper) != (player_id in lower)
    assert groups[0][0] in upper and groups[1][0] in lower


def test_six_groups_cross_pairing_with_byes():
    """6 组 = 12 人 → 16 签：最强的 4 名（各组第一按组序）轮空，其余首尾交叉。

    该规模属于未冻结配置：轮空落位是 deterministic compatibility implementation。
    """
    groups = [[index * 10 + 1, index * 10 + 2] for index in range(1, 7)]

    rounds_spec = build_bracket(_groups(groups), allow_extended=True)
    assert [len(round_) for round_ in rounds_spec] == [8, 4, 2, 1]

    first = rounds_spec[0]
    byes = {
        m["player_a_id"] if m["player_b_id"] is None else m["player_b_id"]
        for m in first
        if (m["player_a_id"] is None) != (m["player_b_id"] is None)
    }
    assert byes == {group[0] for group in groups[:4]}

    real = [
        (m["player_a_id"], m["player_b_id"])
        for m in first
        if m["player_a_id"] is not None and m["player_b_id"] is not None
    ]
    assert len(real) == 4
    group_of = {pid: index for index, group in enumerate(groups) for pid in group}
    assert all(group_of[a] != group_of[b] for a, b in real)
    assert set(real) == {
        (groups[4][0], groups[5][1]),
        (groups[5][0], groups[4][1]),
        (groups[0][1], groups[3][1]),
        (groups[1][1], groups[2][1]),
    }


def test_top_two_seeds_in_different_halves():
    """1号种子(11=A1)在上半区，2号种子(21=B1)在下半区，最早决赛相遇。"""
    first = _first_round_pairs([[11, 12], [21, 22], [31, 32], [41, 42]])
    # QF1/QF2 进 SF1（上半区），QF3/QF4 进 SF2（下半区）
    top = first[:2]
    bottom = first[2:]

    def ids(matches):
        return {pid for pair in matches for pid in pair}

    assert 11 in ids(top) and 11 not in ids(bottom)     # 1号种子上半区
    assert 21 in ids(bottom) and 21 not in ids(top)     # 2号种子下半区
    # 3/4号种子分别进上下半区的另一场
    assert 31 in ids(top) and 41 in ids(bottom)


def test_no_duplicate_players_across_first_round():
    qualifiers = _groups([[11, 12], [21, 22], [31, 32], [41, 42]])
    rounds_spec = build_bracket(qualifiers)
    players = []
    for m in rounds_spec[0]:
        players.extend([m["player_a_id"], m["player_b_id"]])
    assert len(players) == len(set(players)) == 8


def test_slots_empty_in_later_rounds():
    qualifiers = _groups([[11, 12], [21, 22], [31, 32], [41, 42]])
    rounds_spec = build_bracket(qualifiers)
    for r in (1, 2):
        for m in rounds_spec[r]:
            assert m["player_a_id"] is None
            assert m["player_b_id"] is None
            assert m["round"] == r + 1


def test_16_players_four_rounds():
    groups = [[i * 10 + 1, i * 10 + 2] for i in range(1, 9)]
    rounds_spec = build_bracket(groups)
    assert [len(r) for r in rounds_spec] == [8, 4, 2, 1]
    # 16 名首轮选手互不重复
    players = [pid for m in rounds_spec[0] for pid in (m["player_a_id"], m["player_b_id"])]
    assert len(set(players)) == 16


def test_two_groups_four_players():
    qualifiers = _groups([[11, 12], [21, 22]])
    rounds_spec = build_bracket(qualifiers)
    assert [len(r) for r in rounds_spec] == [2, 1]
    pairs = [(m["player_a_id"], m["player_b_id"]) for m in rounds_spec[0]]
    assert pairs == [(11, 22), (21, 12)]


def test_six_qualifiers_rejected():
    with pytest.raises(ValueError):
        build_bracket(_groups([[11, 12], [21, 22], [31, 32]]))


def test_three_per_group_rejected():
    with pytest.raises(ValueError):
        build_bracket([[11, 12, 13], [21, 22, 23]])


def test_single_group_rejected():
    with pytest.raises(ValueError):
        build_bracket([[11, 12]])


def test_duplicate_qualifier_rejected():
    with pytest.raises(ValueError):
        build_bracket(_groups([[11, 12], [11, 22]]))


@pytest.mark.parametrize(
    "qualifiers",
    [
        [[11], [21, 22], [31], [41, 42]],
        [[11, 12, 13, 14], [21], [31]],
    ],
)
def test_extended_bracket_avoids_same_group_when_feasible(qualifiers):
    group_by_player = {
        player_id: group_index
        for group_index, group in enumerate(qualifiers)
        for player_id in group
    }

    first_round = build_bracket(qualifiers, allow_extended=True)[0]

    real_pairs = [
        (match["player_a_id"], match["player_b_id"])
        for match in first_round
        if match["player_a_id"] is not None and match["player_b_id"] is not None
    ]
    assert all(group_by_player[a] != group_by_player[b] for a, b in real_pairs)
