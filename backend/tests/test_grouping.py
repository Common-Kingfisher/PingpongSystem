"""分组领域算法测试：不丢人、不重复、人数均衡、可复现。"""

import random

import pytest

from app.domain.grouping import auto_group


def test_24_players_into_4_groups_each_6():
    ids = list(range(1, 25))
    groups = auto_group(ids, 4, random.Random(42))
    assert len(groups) == 4
    assert sorted(len(g) for g in groups) == [6, 6, 6, 6]
    flat = sorted(pid for g in groups for pid in g)
    assert flat == ids  # 不丢人、不重复


def test_25_players_balanced_within_one():
    ids = list(range(1, 26))
    groups = auto_group(ids, 4, random.Random(7))
    sizes = sorted(len(g) for g in groups)
    assert sizes == [6, 6, 6, 7]  # 人数尽量均衡
    assert max(sizes) - min(sizes) <= 1
    flat = sorted(pid for g in groups for pid in g)
    assert flat == ids


def test_6_players_into_3_groups():
    ids = list(range(1, 7))
    groups = auto_group(ids, 3, random.Random(3))
    assert sorted(len(g) for g in groups) == [2, 2, 2]
    assert sorted(pid for g in groups for pid in g) == ids


def test_same_seed_same_result():
    ids = list(range(1, 25))
    a = auto_group(ids, 4, random.Random(99))
    b = auto_group(ids, 4, random.Random(99))
    assert a == b


def test_different_seeds_different_result():
    ids = list(range(1, 25))
    a = auto_group(ids, 4, random.Random(1))
    b = auto_group(ids, 4, random.Random(2))
    assert a != b


def test_zero_players_creates_empty_groups():
    assert auto_group([], 4, random.Random(1)) == [[], [], [], []]


def test_fewer_players_than_groups():
    groups = auto_group([1, 2], 4, random.Random(1))
    assert sorted(len(g) for g in groups) == [0, 0, 1, 1]
    assert sorted(pid for g in groups for pid in g) == [1, 2]


def test_invalid_group_count_rejected():
    with pytest.raises(ValueError):
        auto_group([1, 2, 3], 0, random.Random(1))
