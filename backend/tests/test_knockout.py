"""淘汰赛 bracket 算法测试：对阵结构、无重复、prev 追溯、范围限制。"""

import pytest

from app.domain.knockout import build_bracket


def _groups(ids_by_group):
    """[[g1_1, g1_2], [g2_1, g2_2], ...]"""
    return [list(g) for g in ids_by_group]


def test_4_groups_cross_pairing():
    """上半区 A1-B2 / C1-D2，下半区 B1-A2 / D1-C2。"""
    qualifiers = _groups([[11, 12], [21, 22], [31, 32], [41, 42]])
    rounds_spec = build_bracket(qualifiers)
    # 三轮：4 + 2 + 1
    assert [len(r) for r in rounds_spec] == [4, 2, 1]

    first = rounds_spec[0]
    pairs = [(m["player_a_id"], m["player_b_id"]) for m in first]
    assert pairs == [(11, 22), (31, 42), (21, 12), (41, 32)]


def test_top_two_seeds_in_different_halves():
    """1号种子(11=A1)在上半区，2号种子(21=B1)在下半区，最早决赛相遇。"""
    qualifiers = _groups([[11, 12], [21, 22], [31, 32], [41, 42]])
    rounds_spec = build_bracket(qualifiers)
    first = rounds_spec[0]
    # QF1/QF2 进 SF1（上半区），QF3/QF4 进 SF2（下半区）
    top = first[:2]
    bottom = first[2:]

    def ids(matches):
        return {pid for m in matches for pid in (m["player_a_id"], m["player_b_id"])}

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
