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


def build_bracket(qualifiers_by_group: list[list[int]]) -> list[list[dict[str, Any]]]:
    """根据各组的晋级名单生成轮次规格。

    qualifiers_by_group: 按小组顺序、每组按名次排列的晋级选手 id 列表。
    返回 rounds_spec，rounds_spec[r] 为第 r 轮（r 从 1 起）的比赛列表，每项：
      {"round": r, "match_index": idx, "player_a_id": id|None, "player_b_id": id|None}
    首轮选手直接填入；后续轮次为 None 槽位，由服务层按 prev 关系接续。
    """
    if not qualifiers_by_group:
        raise ValueError("没有可晋级的选手")
    q_per_group = len(qualifiers_by_group[0])
    if q_per_group != 2:
        raise ValueError("淘汰赛仅支持每组晋级 2 人的交叉对阵")
    if any(len(q) != q_per_group for q in qualifiers_by_group):
        raise ValueError("各组晋级人数不一致")
    if len(qualifiers_by_group) < 2 or len(qualifiers_by_group) % 2 != 0:
        raise ValueError("需要偶数个小组（至少 2 个）才能生成交叉淘汰赛")

    total = len(qualifiers_by_group) * q_per_group
    if total < 2 or (total & (total - 1)) != 0:
        raise ValueError("晋级总人数必须是 2 的幂（8 / 16 / 32）")

    # 首轮交叉对阵
    first_pairs: list[tuple[int, int]] = []
    for gi in range(0, len(qualifiers_by_group), 2):
        g1 = qualifiers_by_group[gi]
        g2 = qualifiers_by_group[gi + 1]
        first_pairs.append((g1[0], g2[1]))   # 组1 第一 vs 组2 第二
        first_pairs.append((g2[0], g1[1]))   # 组2 第一 vs 组1 第二

    seen: set[int] = set()
    for a, b in first_pairs:
        for pid in (a, b):
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
