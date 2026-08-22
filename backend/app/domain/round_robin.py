"""小组循环赛编排算法（纯函数）。

使用固定轮转法（circle method）生成单循环赛程：
- 任意两名选手恰好交手一次；
- 不会出现自己 vs 自己；
- 人数为奇数时插入"轮空"（bye）占位，不影响真实对局数；
- 同一轮内任何选手至多出现一次（便于后续球台调度）。

返回 [(round, player_a, player_b), ...]，round 从 1 开始。
"""

from typing import Sequence


def round_robin(player_ids: Sequence[int]) -> list[tuple[int, int, int]]:
    """生成 player_ids 的单循环赛程。选手少于 2 人时返回空列表。"""
    ids = list(player_ids)
    n = len(ids)
    if n < 2:
        return []

    # 奇数人数补一个轮空位（None），使轮转表为偶数
    if n % 2 == 1:
        ids = ids + [None]

    fixed = ids[0]
    rotating = ids[1:]
    rounds = len(ids) - 1  # 偶数 m 时轮数为 m-1

    schedule: list[tuple[int, int, int]] = []
    for r in range(1, rounds + 1):
        # 首位固定选手 vs rotating[0]；其余首尾配对
        pairs = [(fixed, rotating[0])]
        mid = len(rotating) // 2
        for i in range(1, mid + 1):
            pairs.append((rotating[i], rotating[-i]))
        # 去掉含轮空的配对
        for a, b in pairs:
            if a is None or b is None:
                continue
            schedule.append((r, a, b))
        # 末尾元素移到最前（轮转）
        rotating = [rotating[-1]] + rotating[:-1]

    return schedule
