"""自动分组算法（纯函数，与 UI / DB 解耦）。

策略：随机洗牌后按顺序轮流放入各组（round-robin），
保证：不丢人、不重复、各组人数差不超过 1。
"""

import random
from typing import Sequence


def auto_group(
    player_ids: Sequence[int],
    group_count: int,
    rng: random.Random | None = None,
) -> list[list[int]]:
    """把 player_ids 随机、均衡地分为 group_count 组。

    返回 group_count 个列表，每个列表是选手 id 列表（顺序即组内顺序）。
    允许某些组为空（如选手数少于组数时）。
    """
    if group_count <= 0:
        raise ValueError("group_count 必须为正整数")

    rng = rng or random.Random()
    shuffled = list(player_ids)
    rng.shuffle(shuffled)

    groups: list[list[int]] = [[] for _ in range(group_count)]
    for index, player_id in enumerate(shuffled):
        groups[index % group_count].append(player_id)
    return groups
