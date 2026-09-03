"""淘汰赛 bracket 生成（纯函数，与 UI / DB 解耦）。

对阵规则（每组前 2 名交叉）：
  以相邻两组为一对，A1 vs B2、B1 vs A2、C1 vs D2、D1 vs C2 ……
后续轮次先生成空槽位（player=None），由胜者晋级填入，保证：
  - 晋级来源可追踪（prev 指向上一轮的比赛）；
  - 已淘汰选手不会出现在后续轮次（槽位由胜者唯一填充）。

范围限制（明确拒绝而非编造）：
  - 仅支持每组晋级 2 人；
  - 需要偶数个小组（≥2）；
  - 晋级总人数必须是 2 的幂（8 / 16 / 32）。
"""

from typing import Any


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
    q_per_group = len(qualifiers_by_group[0])
    if q_per_group < 1:
        raise ValueError("每组至少需要 1 名晋级者")
    if any(len(q) != q_per_group for q in qualifiers_by_group):
        raise ValueError("各组晋级人数不一致")
    total = len(qualifiers_by_group) * q_per_group
    if total < 2:
        raise ValueError("至少需要 2 名晋级者")
    if not allow_extended:
        if q_per_group != 2:
            raise ValueError("淘汰赛仅支持每组晋级 2 人的交叉对阵")
        if len(qualifiers_by_group) < 2 or len(qualifiers_by_group) % 2 != 0:
            raise ValueError("需要偶数个小组（至少 2 个）才能生成交叉淘汰赛")
        if (total & (total - 1)) != 0:
            raise ValueError("晋级总人数必须是 2 的幂（8 / 16 / 32）")

    # 首轮交叉对阵：先把各"相邻组对"的"上半区"（组1第一 vs 组2第二）依次放下，
    # 再把"下半区"（组2第一 vs 组1第二）依次放下。
    # 这样 1号种子(A1) 与 2号种子(B1) 分处上下半区，最早决赛相遇；3/4号种子同理。
    # 例如 4 组：QF1=A1-B2, QF2=C1-D2, QF3=B1-A2, QF4=D1-C2
    # 保留队友版最常用的“偶数组、每组前二”交叉签位，其他配置走通用蛇形签位。
    if q_per_group == 2 and len(qualifiers_by_group) >= 2 and len(qualifiers_by_group) % 2 == 0 and (total & (total - 1)) == 0:
        pairs_of_groups = [
            (qualifiers_by_group[i], qualifiers_by_group[i + 1])
            for i in range(0, len(qualifiers_by_group), 2)
        ]
        first_pairs: list[tuple[int | None, int | None]] = []
        for g1, g2 in pairs_of_groups:
            first_pairs.append((g1[0], g2[1]))
        for g1, g2 in pairs_of_groups:
            first_pairs.append((g2[0], g1[1]))
    else:
        seeded: list[int] = []
        for rank_index in range(q_per_group):
            layer = [group[rank_index] for group in qualifiers_by_group]
            if rank_index % 2:
                layer.reverse()
            seeded.extend(layer)
        bracket_size = 1
        while bracket_size < len(seeded):
            bracket_size *= 2
        slots: list[int | None] = seeded + [None] * (bracket_size - len(seeded))
        half = bracket_size // 2
        first_pairs = [(slots[i], slots[-1 - i]) for i in range(half)]

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
