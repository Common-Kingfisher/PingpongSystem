"""团体淘汰签生成（A6.4）——纯函数，不访问数据库。

规则源：[`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`](../../../docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md)。

## 与个人赛淘汰签的关系

**不使用**个人赛的配对规则（`domain/knockout.py` 的 `_mirror_first_pairs` 等），
也**不复用**个人赛的种子/名次推导。团体签的输入是"A6.3 已确认的晋级队伍"，
按**小组顺序 + 组内晋级名次**落位，规则见下。

唯一复用的是 `domain/knockout.build_bracket()` 的**纯结构**能力
（"给定一个已排好的首轮名单，生成后续轮次的空槽位与 prev 依赖关系"），
它是通用的签表骨架计算，不含任何个人赛语义。首轮配对由本模块自己决定。

## 首轮配对（V1，按小组顺序，相邻组交叉）

把小组按 `groups.sort_order` 两两分组；每一对小组（g1, g2）生成两场：

    g1 第 1 名 vs g2 第 2 名
    g2 第 1 名 vs g1 第 2 名

    4 组 × 每组前 2：QF1 = A1-B2, QF2 = B1-A2, QF3 = C1-D2, QF4 = D1-C2
    2 组 × 每组前 2：QF1 = A1-B2, QF2 = B1-A2

首轮各场的先后顺序即上面列出的顺序，后续轮次由**相邻两场**的胜者会合
（第 1、2 场胜者进同一场半决赛，第 3、4 场胜者进另一场）。因此：
- 同一小组的两支队伍分处不同半区，最早在决赛相遇；
- 同名次之间不会首轮相遇（每组第 1 名只打另一组的第 2 名）。

**确定性**：输入相同 → 输出完全一致；不使用随机数、不按数据库 id 排序、
不做任何"按 id 打破并列"的兜底。
"""

from typing import Any, Sequence

from .knockout import build_bracket


class TeamKnockoutError(Exception):
    """淘汰签生成输入不合法。"""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def expected_round_count(total_teams: int) -> int:
    """给定晋级队伍总数，返回单败淘汰需要的轮数（不足 2 支返回 0）。"""
    if total_teams < 2:
        return 0
    rounds = 0
    size = 1
    while size < total_teams:
        size *= 2
        rounds += 1
    return rounds


def round_display_name(round_no: int, total_rounds: int) -> str:
    """轮次展示名（只用于展示/导出，不参与任何判定）。

    - 最后一轮 → `Final`；
    - 倒数第二轮 → `Semi Final`；
    - 倒数第三轮 → `Quarter Final`；
    - 更早的轮次 → `Round of N`（N = 该轮理论参赛队伍数）。
    """
    if round_no >= total_rounds:
        return "Final"
    if round_no == total_rounds - 1:
        return "Semi Final"
    if round_no == total_rounds - 2:
        return "Quarter Final"
    remaining = 2 ** (total_rounds - round_no + 1)
    return f"Round of {remaining}"


def build_first_round_pairs(
    qualifiers_by_group: Sequence[Sequence[int]],
) -> list[tuple[int, int]]:
    """按小组顺序 + 组内晋级名次生成首轮对阵（相邻组交叉，确定性）。

    `qualifiers_by_group`：按小组顺序排列，每组是"已确认晋级的队伍 id，按组内晋级名次"。
    V1 要求每组晋级人数相同且为 2（见 `validate_groups`），从而每个相邻组对正好两场。
    """
    _validate_groups(qualifiers_by_group)

    per_group = len(qualifiers_by_group[0])
    pairs: list[tuple[int, int]] = []
    for index in range(0, len(qualifiers_by_group), 2):
        first = qualifiers_by_group[index]
        second = qualifiers_by_group[index + 1]
        # 相邻两组交叉。`_validate_groups` 已保证 per_group == 2，因此每个组对正好两场：
        #   first 第 1 名 vs second 第 2 名   （A1-B2）
        #   second 第 1 名 vs first 第 2 名   （B1-A2）
        pairs.append((first[0], second[1]))
        pairs.append((second[0], first[1]))
    return pairs


def _validate_groups(qualifiers_by_group: Sequence[Sequence[int]]) -> None:
    if not qualifiers_by_group or not any(qualifiers_by_group):
        raise TeamKnockoutError("没有已确认晋级的队伍，不能生成团体淘汰签")
    if any(not group for group in qualifiers_by_group):
        raise TeamKnockoutError("每个小组都必须至少有 1 支晋级队伍")

    per_group = len(qualifiers_by_group[0])
    if any(len(group) != per_group for group in qualifiers_by_group):
        raise TeamKnockoutError(
            "各组晋级队伍数量不一致，当前版本只支持各组晋级人数相同的团体淘汰签"
        )
    if per_group != 2:
        raise TeamKnockoutError(
            f"当前版本只支持每组晋级 2 支队伍的团体淘汰签（收到每组 {per_group} 支）"
        )
    if len(qualifiers_by_group) < 2 or len(qualifiers_by_group) % 2 != 0:
        raise TeamKnockoutError("需要偶数个小组（至少 2 个）才能生成团体淘汰签")

    seeds = [team_id for group in qualifiers_by_group for team_id in group]
    if len(set(seeds)) != len(seeds):
        raise TeamKnockoutError("晋级名单中存在重复队伍，不能生成团体淘汰签")
    total = len(seeds)
    if total & (total - 1):
        # 非 2 的幂：需要轮空，而团体赛的轮空规则尚未冻结（见规则文档「未冻结」）。
        raise TeamKnockoutError(
            f"当前版本要求晋级队伍总数为 2 的幂（收到 {total} 支）："
            f"团体淘汰签的轮空规则尚未冻结"
        )


def build_team_bracket(
    qualifiers_by_group: Sequence[Sequence[int]],
) -> list[list[dict[str, Any]]]:
    """生成团体淘汰签的全部轮次规格。

    返回 `rounds_spec`：第 r 轮（从 1 起）的比赛列表，每项
    `{"round", "match_index", "team_a_id", "team_b_id"}`。
    首轮填入已确认的晋级队伍；后续轮次槽位为 `None`，由服务层按 prev 关系接续
    （与个人赛淘汰签的"先建骨架、胜者晋级填入"保持一致）。
    """
    pairs = build_first_round_pairs(qualifiers_by_group)
    total = sum(len(group) for group in qualifiers_by_group)
    total_rounds = expected_round_count(total)

    # 复用通用骨架计算：只取它的**轮次结构**（后续轮次的空槽位数量），
    # 首轮对阵使用本模块自己算出的 pairs，绝不采用它返回的首轮配对。
    skeleton = build_bracket([list(range(total))], allow_extended=True)
    if len(skeleton) != total_rounds:  # pragma: no cover - 防御：轮次数必须一致
        raise TeamKnockoutError("淘汰签轮次结构计算不一致")
    if len(skeleton[0]) != len(pairs):  # pragma: no cover - 防御：首轮场次必须一致
        raise TeamKnockoutError("淘汰签首轮场次数量不一致")

    rounds_spec: list[list[dict[str, Any]]] = []
    for round_index, round_skeleton in enumerate(skeleton):
        round_no = round_index + 1
        specs: list[dict[str, Any]] = []
        for match_index in range(len(round_skeleton)):
            if round_no == 1:
                a, b = pairs[match_index]
            else:
                a = b = None
            specs.append(
                {
                    "round": round_no,
                    "match_index": match_index,
                    "team_a_id": a,
                    "team_b_id": b,
                }
            )
        rounds_spec.append(specs)
    return rounds_spec
