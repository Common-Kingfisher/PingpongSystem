"""淘汰赛 bracket 算法测试：对阵结构、无重复、prev 追溯、范围限制。"""

import pytest

from app.domain.knockout import build_bracket


def _groups(ids_by_group):
    """[[g1_1, g1_2], [g2_1, g2_2], ...]"""
    return [list(g) for g in ids_by_group]


def test_4_groups_cross_pairing():
    """A1-B2 / B1-A2 / C1-D2 / D1-C2。"""
    qualifiers = _groups([[11, 12], [21, 22], [31, 32], [41, 42]])
    rounds_spec = build_bracket(qualifiers)
    # 三轮：4 + 2 + 1
    assert [len(r) for r in rounds_spec] == [4, 2, 1]

    first = rounds_spec[0]
    pairs = [(m["player_a_id"], m["player_b_id"]) for m in first]
    assert pairs == [(11, 22), (21, 12), (31, 42), (41, 32)]


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
