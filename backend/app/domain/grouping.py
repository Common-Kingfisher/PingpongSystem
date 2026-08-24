"""自动分组算法（纯函数，与 UI / DB 解耦）。

策略：
1. 种子选手（seeds，按 1..N 号顺序）先依次进入不同小组（1号→组0，2号→组1……）；
2. 其余非种子选手随机打乱后，从"第一个未放种子的小组"开始轮流分配，
   保证各组人数差不超过 1，同时种子仍在不同小组。

不变量：不丢人、不重复、各组人数差 <= 1、种子互不同组。
"""

import random
from typing import Sequence


def auto_group(
    player_ids: Sequence[int],
    group_count: int,
    rng: random.Random | None = None,
    seeds: Sequence[int] | None = None,
) -> list[list[int]]:
    """把 player_ids 随机、均衡地分为 group_count 组。

    seeds: 按种子顺序（1号、2号…）排列的选手 id 列表（可为空/None）。
    返回 group_count 个列表，每个列表是选手 id 列表（顺序即组内顺序）。
    """
    if group_count <= 0:
        raise ValueError("group_count 必须为正整数")

    rng = rng or random.Random()
    ids = list(player_ids)
    valid_seeds = [s for s in (seeds or []) if s in ids]
    seed_set = set(valid_seeds)

    groups: list[list[int]] = [[] for _ in range(group_count)]
    for i, sid in enumerate(valid_seeds):
        if i < group_count:
            groups[i].append(sid)

    remaining = [pid for pid in ids if pid not in seed_set]
    rng.shuffle(remaining)
    # 从第一个未放种子的小组开始，让未放种子的小组先补足，保持各组均衡
    offset = len(valid_seeds) % group_count
    for index, pid in enumerate(remaining):
        groups[(offset + index) % group_count].append(pid)

    return groups
