"""淘汰赛 bracket 生成（纯函数，与 UI / DB 解耦）。

对阵规则（已冻结：偶数组、每组前 2 名“首尾交叉”）：
  设 N 个小组 G1…GN，各组第 1 名与“反向组”的第 2 名配对：

      QF1: G1-1 vs GN-2      QF2: G3-1 vs G(N-2)-2   …
      QF3: G2-1 vs G(N-1)-2  QF4: G4-1 vs G(N-3)-2   …

  4 组时即 A1-D2、C1-B2、B1-C2、D1-A2。
  配对按“偶序号上半区、奇序号下半区”排列，因此：
  - 同一组的两名选手分处不同半区，最早在决赛相遇；
  - 1/2 号种子（G1-1、G2-1）分处不同半区，最高种子路径受保护。
  签表规模不是 2 的幂时（如 6 组 = 12 人 → 16 签），由最强的选手轮空，
  其余选手仍按首尾交叉配对；轮空落位为最小实现，规则尚未冻结。

后续轮次先生成空槽位（player=None），由胜者晋级填入，保证：
  - 晋级来源可追踪（prev 指向上一轮的比赛）；
  - 已淘汰选手不会出现在后续轮次（槽位由胜者唯一填充）。

**未冻结规则**：奇数组、各组晋级人数不一致、以及需要轮空的规模，走下方
`_extended_first_pairs` 的通用（蛇形分层 + 轮空贪心）路径。该路径只是兼容
所需的最小实现，会议尚未确认其赛制语义，不要当成正式规则引用。
"""

from typing import Any


def _spread_order(slot_count: int) -> list[int]:
    """标准摊开顺序：1 号位、另一半区首位、第二半区首位、第四半区首位……

    用于把轮空（即“最高的几个种子”）均匀摊到签表各区，避免种子扎堆。
    """
    if slot_count <= 1:
        return [0]
    half = slot_count // 2
    order: list[int] = []
    for slot in _spread_order(half):
        order.append(slot)
        order.append(slot + half)
    return order


def _mirror_first_pairs(qualifiers_by_group: list[list[int]]) -> list[tuple[int | None, int | None]]:
    """偶数组、每组 2 人：首尾交叉配对（已冻结规则）。

    强弱序 S = [各组第 1 名（按组序），各组第 2 名（按组序）]。
    - 无轮空时：第 k 强与倒数第 k 强配对，即 G(i)-1 vs G(N-1-i)-2；
    - 需要轮空时：最强的若干人轮空，其余人仍按首尾交叉配对；
    - 配对顺序为“偶序号在前（上半区）、奇序号在后（下半区）”，
      保证同组两名选手分处不同半区、1/2 号种子分处不同半区。
    """
    strength = [group[0] for group in qualifiers_by_group] + [
        group[1] for group in qualifiers_by_group
    ]
    total = len(strength)
    bracket_size = 1
    while bracket_size < total:
        bracket_size *= 2
    slot_count = bracket_size // 2
    bye_count = bracket_size - total
    bye_players = strength[:bye_count]
    remaining = strength[bye_count:]
    mirror_pairs = [
        (remaining[index], remaining[-1 - index])
        for index in range(len(remaining) // 2)
    ]
    upper_pairs = [pair for index, pair in enumerate(mirror_pairs) if index % 2 == 0]
    lower_pairs = [pair for index, pair in enumerate(mirror_pairs) if index % 2 == 1]
    ordered_pairs = upper_pairs + lower_pairs

    if bye_count == 0:
        return ordered_pairs

    # 轮空落位（未冻结的最小实现）：上下半区各分一半轮空，半区内按摊开顺序落位，
    # 轮空按强弱顺序轮流进入上下半区，从而保持 1/2 号种子分处不同半区。
    slots: list[tuple[int | None, int | None] | None] = [None] * slot_count
    half_size = slot_count // 2
    half_spread = _spread_order(half_size)
    byes_per_half = bye_count // 2
    bye_slots: list[list[int]] = [
        [slot for slot in half_spread[:byes_per_half]],
        [half_size + slot for slot in half_spread[:byes_per_half]],
    ]
    real_slots: list[list[int]] = [
        [slot for slot in range(0, half_size) if slot not in bye_slots[0]],
        [slot for slot in range(half_size, slot_count) if slot not in bye_slots[1]],
    ]
    for index, player in enumerate(bye_players):
        half = index % 2
        slots[bye_slots[half][index // 2]] = (player, None)
    for half, pairs in enumerate((upper_pairs, lower_pairs)):
        for slot, pair in zip(real_slots[half], pairs):
            slots[slot] = pair
    if any(slot is None for slot in slots):  # pragma: no cover - 防御：落位数量必须正好填满
        raise ValueError("轮空与首轮对阵数量不匹配")
    return [slot for slot in slots if slot is not None]


def _extended_first_pairs(
    seeded: list[tuple[int, int]], bracket_size: int
) -> list[tuple[int | None, int | None]]:
    """为扩展签位分配轮空并贪心生成跨组首轮对阵（未冻结规则，仅兼容需要）。"""
    bye_count = bracket_size - len(seeded)
    remaining_count = len(seeded) - bye_count
    group_counts: dict[int, int] = {}
    for _, group_index in seeded:
        group_counts[group_index] = group_counts.get(group_index, 0) + 1

    # 若某组人数超过非轮空位的一半，优先把该组高排位选手设为轮空，
    # 使余下选手存在全跨组配对解；其余轮空再按原种子顺序分配。
    required_byes = {
        group_index: max(0, count - remaining_count // 2)
        for group_index, count in group_counts.items()
    }
    bye_indexes: set[int] = set()
    for group_index, required in required_byes.items():
        candidates = [
            index for index, (_, group) in enumerate(seeded)
            if group == group_index
        ]
        bye_indexes.update(candidates[:required])
    for index in range(len(seeded)):
        if len(bye_indexes) >= bye_count:
            break
        bye_indexes.add(index)

    remaining = [item for index, item in enumerate(seeded) if index not in bye_indexes]
    remaining_group_counts: dict[int, int] = {}
    for _, group_index in remaining:
        remaining_group_counts[group_index] = remaining_group_counts.get(group_index, 0) + 1
    if len(bye_indexes) != bye_count or (
        remaining_group_counts
        and max(remaining_group_counts.values()) > len(remaining) // 2
    ):
        slots: list[int | None] = [participant for participant, _ in seeded] + [None] * bye_count
        return [(slots[index], slots[-1 - index]) for index in range(bracket_size // 2)]

    by_group: dict[int, list[int]] = {}
    for participant, group_index in remaining:
        by_group.setdefault(group_index, []).append(participant)
    pairs: list[tuple[int | None, int | None]] = [
        (seeded[index][0], None) for index in sorted(bye_indexes)
    ]
    while True:
        available = sorted(
            ((len(participants), group_index) for group_index, participants in by_group.items() if participants),
            key=lambda item: (-item[0], item[1]),
        )
        if not available:
            return pairs
        if len(available) < 2:
            slots = [participant for participant, _ in seeded] + [None] * bye_count
            return [(slots[index], slots[-1 - index]) for index in range(bracket_size // 2)]
        first_group, second_group = available[0][1], available[1][1]
        pairs.append((by_group[first_group].pop(0), by_group[second_group].pop(0)))


def build_bracket(
    qualifiers_by_group: list[list[int]], allow_extended: bool = False
) -> list[list[dict[str, Any]]]:
    """根据各组的晋级名单生成轮次规格。

    qualifiers_by_group: 按小组顺序、每组按名次排列的晋级选手 id 列表。
    返回 rounds_spec，rounds_spec[r] 为第 r 轮（r 从 1 起）的比赛列表，每项：
      {"round": r, "match_index": idx, "player_a_id": id|None, "player_b_id": id|None}
    首轮选手直接填入；后续轮次为 None 槽位，由服务层按 prev 关系接续。
    """
    if not qualifiers_by_group or not any(qualifiers_by_group):
        raise ValueError("没有可晋级的选手")
    if any(not group for group in qualifiers_by_group):
        raise ValueError("每组至少需要 1 名晋级者")
    q_per_group = len(qualifiers_by_group[0])
    equal_qualifier_count = all(len(group) == q_per_group for group in qualifiers_by_group)
    total = sum(len(group) for group in qualifiers_by_group)
    if total < 2:
        raise ValueError("至少需要 2 名晋级者")
    if not allow_extended:
        if not equal_qualifier_count:
            raise ValueError("各组晋级人数不一致")
        if q_per_group != 2:
            raise ValueError("淘汰赛仅支持每组晋级 2 人的交叉对阵")
        if len(qualifiers_by_group) < 2 or len(qualifiers_by_group) % 2 != 0:
            raise ValueError("需要偶数个小组（至少 2 个）才能生成交叉淘汰赛")

    # 首轮交叉对阵（已冻结规则，偶数小组 × 每组前二）：首尾交叉。
    # 4 组即 QF1=A1-D2、QF2=C1-B2、QF3=B1-C2、QF4=D1-A2；
    # 2 组即 A1-B2、B1-A2；8 组时 G1-1 对 G8-2，依此类推。
    # 上半区先放“偶序号”对阵，再放下半区的“奇序号”对阵，使同组两人与 1/2 号种子
    # 分处不同半区。总人数不是 2 的幂时（如 6 组 = 12 人）由最强选手轮空。
    if (
        equal_qualifier_count
        and q_per_group == 2
        and len(qualifiers_by_group) >= 2
        and len(qualifiers_by_group) % 2 == 0
    ):
        first_pairs = _mirror_first_pairs(qualifiers_by_group)
    else:
        seeded: list[tuple[int, int]] = []
        for rank_index in range(max(len(group) for group in qualifiers_by_group)):
            layer = [
                (group[rank_index], group_index)
                for group_index, group in enumerate(qualifiers_by_group)
                if rank_index < len(group)
            ]
            if rank_index % 2:
                layer.reverse()
            seeded.extend(layer)
        bracket_size = 1
        while bracket_size < len(seeded):
            bracket_size *= 2
        first_pairs = _extended_first_pairs(seeded, bracket_size)

    seen: set[int] = set()
    for a, b in first_pairs:
        for pid in (a, b):
            if pid is None:
                continue
            if pid in seen:
                raise ValueError("晋级名单中存在重复选手")
            seen.add(pid)

    rounds_spec: list[list[dict[str, Any]]] = []
    round_players: list[tuple[int | None, int | None]] = first_pairs
    r = 1
    while True:
        round_spec = [
            {
                "round": r,
                "match_index": idx,
                "player_a_id": a,
                "player_b_id": b,
            }
            for idx, (a, b) in enumerate(round_players)
        ]
        rounds_spec.append(round_spec)
        if len(round_players) == 1:
            break
        r += 1
        round_players = [(None, None)] * (len(round_players) // 2)

    return rounds_spec
