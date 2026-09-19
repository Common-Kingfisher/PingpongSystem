"""团体小组排名（Team Group Standings V1）——纯算法，不访问数据库。

**唯一业务规则源**：[`docs/TEAM_GROUP_RULES_V1.md`](../../../docs/TEAM_GROUP_RULES_V1.md)
（A6.2）。本模块**不得**根据"常见乒乓球规则"、个人赛 `domain/ranking.py` 的排序口径、
或任何未写入该文档的惯例自行补规则；改规则先改文档。

## 与个人赛排名的关系

刻意**不复用** `domain/ranking.py` 的排序规则：个人赛是"胜场 → 净胜局 → 积分"，
团体赛是"比赛积分(2/1) → 同分子集重算 → 盘 W/L 比率 → 局 W/L 比率 → 并列区间"，
两者的排序键、同分口径与并列表示都不同。两边各自独立表达，避免一边改动时悄悄影响另一边。

## 输入是"已经标准化的事实"

调用方（`services/team_standings.py`）负责查库并把行整理成
`TeamEntryFact` / `TeamTieFact` / `TeamRubberFact`；本模块只做纯计算，输出稳定的名次行。

## 统计口径（V1）

1. **比赛积分（match points）**：只统计 `status == FINISHED` 且带胜者的对抗；
   胜方 +2、负方 +1；未完成对抗既不计积分，也不计入 `ties_played / ties_won / ties_lost`。
   **不使用 win=1 / loss=0**，也不做"未完成按 0 分"的近似。
2. **盘与局**：只统计**已完成对抗内** `status == FINISHED` 的盘；
   `SKIPPED`（一方提前达到获胜盘数后未打的盘）完全忽略，`PENDING/READY/PLAYING` 同样不计。
   - 盘 W/L 的胜负来源是 `winner_entry_id`；
   - 局 W/L 直接取该盘的 `home_score` / `away_score`（例如 3:1 → 主队局 3 胜 1 负、客队相反），
     **不新增任何逐局小分表**。
3. **比率比较**：交叉乘法，不用浮点作为排序真相；分母为 0 的两种特殊情形见 `compare_ratio`。

所有输出都只依赖传入的事实，因此"每次查询从真实 TeamTie / Rubber 重算"天然成立
（不做累积增量，也没有第二真相源）。
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

#: 比赛积分常量：正常完赛的胜方 2 分、负方 1 分（规则文档 §3）。
MATCH_POINTS_WIN = 2
MATCH_POINTS_LOSS = 1
MATCH_POINTS_NONE = 0

_CMP_GREATER = 1
_CMP_EQUAL = 0
_CMP_LESS = -1
#: 比较不可用（该 key 无法区分这些队伍）——注意它与"相等"不同。
_CMP_UNAVAILABLE = None

#: 事实里使用的状态字面量（沿用既有枚举取值，本模块不新增状态语义）。
TIE_STATUS_FINISHED = "FINISHED"
RUBBER_STATUS_FINISHED = "FINISHED"
ENTRY_STATUS_WITHDRAWN = "WITHDRAWN"


class TeamStandingsError(Exception):
    """排名输入本身不合法（例如事实引用了不属于本组的队伍）。"""


# ------------------------------------------------------------------ 事实输入

@dataclass(frozen=True)
class TeamEntryFact:
    """一支参赛队伍（已标准化的 `entries(entry_type='TEAM')` 事实）。"""

    team_entry_id: int
    team_name: str
    #: ACTIVE / WITHDRAWN（沿用既有 entries.status 口径）。
    status: str = "ACTIVE"


@dataclass(frozen=True)
class TeamRubberFact:
    """一场对抗中的一盘（已标准化的 `team_rubbers` 事实）。"""

    tie_id: int
    sequence: int = 0
    status: str = ""
    winner_entry_id: int | None = None
    #: 本盘局分（该对抗的 A 队 / B 队视角，与 DB 列同义）。
    home_score: int | None = None
    away_score: int | None = None


@dataclass(frozen=True)
class TeamTieFact:
    """一场"A 队 vs B 队"的团体对抗（已标准化的 `team_ties` 事实）。"""

    tie_id: int
    entry_a_id: int
    entry_b_id: int
    #: WAITING / PLAYING / FINISHED（沿用 TeamTieStatus）。
    status: str = ""
    winner_entry_id: int | None = None
    rubbers: tuple[TeamRubberFact, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StandingsFacts:
    """某个小组排名的完整输入事实。

    `entries` 的顺序就是**稳定展示顺序**（服务层按 `entries.id` 升序传入）；
    名次由算法决定，绝不按 id 打破同分。
    """

    entries: tuple[TeamEntryFact, ...]
    ties: tuple[TeamTieFact, ...] = field(default_factory=tuple)

    @property
    def team_entry_ids(self) -> tuple[int, ...]:
        return tuple(entry.team_entry_id for entry in self.entries)


# ------------------------------------------------------------------ 比率比较

def compare_ratio(wins_a: int, losses_a: int, wins_b: int, losses_b: int) -> int | None:
    """比较两个 W/L 比率，返回 1 / 0 / -1，或 `None` 表示**无法比较**。

    - 交叉乘法 `wins_a * losses_b` vs `wins_b * losses_a`（整数比较，无浮点误差）；
    - `wins > 0 且 losses == 0` → 视为 **+∞**：比任何有限比率与 0/0 都大；两侧同为 +∞ → 相等；
    - `wins == 0 且 losses == 0` → **没有数据**：
      * 两侧都是 0/0 → `None`（**无法比较**：两支队都没打过，谁前谁后没有依据）；
      * 一侧 0/0、另一侧有数据 → 结果**是确定的**：有数据的一方要么全胜（比率 +∞）要么全负（比率 0），
        因此按普通数学比较即可（全胜者赢、全负者输）。
    这就是"0/0 既不是赢也不是输"的落地方式：只有**两边都没数据**时才拒绝给出结论。
    """
    a_is_infinite = wins_a > 0 and losses_a == 0
    b_is_infinite = wins_b > 0 and losses_b == 0
    if a_is_infinite and b_is_infinite:
        return _CMP_EQUAL
    if a_is_infinite:
        return _CMP_GREATER
    if b_is_infinite:
        return _CMP_LESS

    a_has_data = wins_a > 0 or losses_a > 0
    b_has_data = wins_b > 0 or losses_b > 0
    if not a_has_data and not b_has_data:
        return _CMP_UNAVAILABLE

    left = wins_a * losses_b
    right = wins_b * losses_a
    if left > right:
        return _CMP_GREATER
    if left < right:
        return _CMP_LESS
    return _CMP_EQUAL


def compare_int(left: int, right: int) -> int:
    """整数降序比较（大者在前）。"""
    if left > right:
        return _CMP_GREATER
    if left < right:
        return _CMP_LESS
    return _CMP_EQUAL


def resolve_ordering(values: Sequence[Any], compare: Callable[[Any, Any], int | None]) -> list[list[int]] | None:
    """把下标 0..n-1 按 `compare` 划分成**有序等价类**。

    - 返回 `None` 表示该 key **不可用**（存在无法比较的一对），调用方应改用下一个 key 或判并列；
    - 否则返回按优劣排序的组列表（每组内部在该 key 上完全相等，组间严格有序）。

    实现：先做一次稳定的插入排序（降序：`compare` 返回 1 表示前者更优、应排在前面），
    再对相邻元素分组，最后校验组边界确实严格优于下一组。
    任何一对不可比较都会让整个 key 失效——这正是"不可比较 ≠ 相等"的落地方式。
    """
    order = list(range(len(values)))
    if not order:
        return []
    for i in range(1, len(order)):
        current = order[i]
        j = i - 1
        while j >= 0:
            result = compare(values[order[j]], values[current])
            if result is None:
                return None
            if result >= _CMP_EQUAL:
                break  # 前一个不劣于 current：插入点就在这里
            order[j + 1] = order[j]
            j -= 1
        order[j + 1] = current

    groups: list[list[int]] = []
    for index in order:
        if groups:
            result = compare(values[groups[-1][0]], values[index])
            if result is None:
                return None
            if result == _CMP_EQUAL:
                groups[-1].append(index)
                continue
        groups.append([index])
    # 组间必须严格有序（防止比较器不自洽时悄悄产出错误顺序）
    for previous, following in zip(groups, groups[1:]):
        if compare(values[previous[0]], values[following[0]]) != _CMP_GREATER:
            return None
    return groups


# ------------------------------------------------------------------ 统计

@dataclass
class _Totals:
    """一支队伍在**当前子集**内的累计统计。"""

    match_points: int = 0
    ties_played: int = 0
    ties_won: int = 0
    ties_lost: int = 0
    rubber_wins: int = 0
    rubber_losses: int = 0
    games_won: int = 0
    games_lost: int = 0


def _accumulate(facts: StandingsFacts, subset: Sequence[int]) -> list[_Totals]:
    """按**当前子集**统计：只累加双方都在 subset 内的对抗（跨组对抗天然被排除）。

    `subset` 是队伍在 `facts.entries` 中的**下标**（`_resolve` 全程只传下标，绝不与 entry id 混用）。
    返回的 `totals` 与 `subset` 等长且**同序**：`totals[i]` 属于 `facts.entries[subset[i]]`。
    """
    #: entry_id → 它在**本子集**内的偏移（不是全局下标）。
    offset_of = {
        facts.entries[entry_index].team_entry_id: offset
        for offset, entry_index in enumerate(subset)
    }
    totals = [_Totals() for _ in subset]
    for tie in facts.ties:
        a_offset = offset_of.get(tie.entry_a_id)
        b_offset = offset_of.get(tie.entry_b_id)
        if a_offset is None or b_offset is None:
            continue  # 对抗的任一方不在当前子集内（含跨组对抗）→ 不参与本次统计
        if tie.status != TIE_STATUS_FINISHED or tie.winner_entry_id is None:
            continue  # 未完成对抗不作为正常完赛结果计入，也不计入 ties_played
        a = totals[a_offset]
        b = totals[b_offset]
        a.ties_played += 1
        b.ties_played += 1
        if tie.winner_entry_id == tie.entry_a_id:
            winner, loser = a, b
        elif tie.winner_entry_id == tie.entry_b_id:
            winner, loser = b, a
        else:
            raise TeamStandingsError(
                f"团体对抗 #{tie.tie_id} 的胜者 {tie.winner_entry_id} 不是对阵双方"
                f"（{tie.entry_a_id} / {tie.entry_b_id}）"
            )
        winner.match_points += MATCH_POINTS_WIN
        winner.ties_won += 1
        loser.match_points += MATCH_POINTS_LOSS
        loser.ties_lost += 1

        for rubber in tie.rubbers:
            if rubber.status != RUBBER_STATUS_FINISHED or rubber.winner_entry_id is None:
                continue  # SKIPPED（以及 PENDING/READY/PLAYING）完全忽略
            if rubber.winner_entry_id == tie.entry_a_id:
                rubber_winner, rubber_loser = a, b
                a_games = rubber.home_score or 0
                b_games = rubber.away_score or 0
            elif rubber.winner_entry_id == tie.entry_b_id:
                rubber_winner, rubber_loser = b, a
                a_games = rubber.away_score or 0
                b_games = rubber.home_score or 0
            else:
                raise TeamStandingsError(
                    f"盘 #{rubber.sequence}（对抗 #{tie.tie_id}）的胜者 {rubber.winner_entry_id} "
                    f"不是对阵双方"
                )
            rubber_winner.rubber_wins += 1
            rubber_loser.rubber_losses += 1
            # 局分按 home/away 归属到 A/B 两侧：home 列属于 entry_a_id，away 列属于 entry_b_id。
            a.games_won += a_games
            a.games_lost += b_games
            b.games_won += b_games
            b.games_lost += a_games
    return totals


# ------------------------------------------------------------------ 主算法

def _resolve(facts: StandingsFacts, subset: Sequence[int]) -> list[list[int]]:
    """递归拆分 tied subset，返回**按名次排好序**的等价类列表。

    **部分区分（partial resolution）语义**：只要某个 ranking key 把子集拆开，
    就对**每一个**子组从 Step 1 重新开始（`subset` 变小、`_accumulate` 只统计子集内对抗），
    而不是拿着下一个 key 直接继续比。子组之间的先后由该 key 的划分结果决定。
    """
    if not subset:
        return []
    if len(subset) == 1:
        return [list(subset)]

    totals = _accumulate(facts, subset)
    # 单位说明：`_accumulate` 返回的 totals 与 `subset` 等长同序，因此
    # `resolve_ordering` 返回的下标是 **subset 的偏移**，必须经 `subset[...]` 换回
    # entries 下标后再递归（两者不能混用）。

    # Step 1：子集内比赛积分（**在该子集内重新计算**，不是全局积分）
    groups = resolve_ordering(totals, lambda x, y: compare_int(x.match_points, y.match_points))
    if groups is None:  # 理论不可达：整数比较永远可用。保守处理为并列。
        return [list(subset)]
    if len(groups) > 1:
        resolved: list[list[int]] = []
        for group in groups:
            resolved.extend(_resolve(facts, [subset[offset] for offset in group]))
        return resolved

    # Step 2：子集内盘 W/L 比率
    groups = resolve_ordering(
        totals,
        lambda x, y: compare_ratio(x.rubber_wins, x.rubber_losses, y.rubber_wins, y.rubber_losses),
    )
    if groups is not None and len(groups) > 1:
        resolved = []
        for group in groups:
            resolved.extend(_resolve(facts, [subset[offset] for offset in group]))
        return resolved

    # Step 3：子集内局 W/L 比率
    groups = resolve_ordering(
        totals,
        lambda x, y: compare_ratio(x.games_won, x.games_lost, y.games_won, y.games_lost),
    )
    if groups is not None and len(groups) > 1:
        resolved = []
        for group in groups:
            resolved.extend(_resolve(facts, [subset[offset] for offset in group]))
        return resolved

    # Step 4：V1 没有下一个可用的 key（不存在 points ratio）→ 并列，交给人工裁定。
    return [list(subset)]


@dataclass
class StandingRow:
    """一支队伍在该小组的名次行。`rank_start == rank_end` 表示名次唯一。"""

    team_entry_id: int
    team_name: str
    status: str
    match_points: int
    ties_played: int
    ties_won: int
    ties_lost: int
    rubber_wins: int
    rubber_losses: int
    games_won: int
    games_lost: int
    rank_start: int
    rank_end: int
    ambiguous: bool
    eligible_for_qualification: bool


def compute_team_group_standings(facts: StandingsFacts) -> list[StandingRow]:
    """计算一个小组的团体排名（V1）。

    返回按名次排序的 `StandingRow` 列表；并列名次用 `rank_start` / `rank_end` 表示
    （**绝不按 id 打破同分**）。
    """
    entries = list(facts.entries)
    if not entries:
        return []
    team_ids = [entry.team_entry_id for entry in entries]
    if len(set(team_ids)) != len(team_ids):
        raise TeamStandingsError("同一个小组里出现了重复的参赛队伍")
    known = set(team_ids)
    for tie in facts.ties:
        for entry_id in (tie.entry_a_id, tie.entry_b_id):
            if entry_id not in known:
                raise TeamStandingsError(
                    f"团体对抗 #{tie.tie_id} 引用了不属于本小组的队伍 {entry_id}"
                )


    # 全部队伍就是一个 subset：下标 0..n-1（`_accumulate` 只接受下标）。
    totals = _accumulate(facts, list(range(len(team_ids))))

    # `_resolve` 返回的顺序就是最终名次顺序：等价类之间已由 Step 1~3 严格区分，
    # 内部顺序不再依赖 id（同一等价类里的所有队伍共享同一个 rank 区间）。
    final_groups = _resolve(facts, list(range(len(team_ids))))

    rows: list[StandingRow] = []
    position = 1
    for group in final_groups:
        rank_start = position
        rank_end = position + len(group) - 1
        ambiguous = len(group) > 1
        for member in sorted(group):
            entry = entries[member]
            stat = totals[member]
            rows.append(
                StandingRow(
                    team_entry_id=entry.team_entry_id,
                    team_name=entry.team_name,
                    status=entry.status,
                    match_points=stat.match_points,
                    ties_played=stat.ties_played,
                    ties_won=stat.ties_won,
                    ties_lost=stat.ties_lost,
                    rubber_wins=stat.rubber_wins,
                    rubber_losses=stat.rubber_losses,
                    games_won=stat.games_won,
                    games_lost=stat.games_lost,
                    rank_start=rank_start,
                    rank_end=rank_end,
                    ambiguous=ambiguous,
                    eligible_for_qualification=entry.status != ENTRY_STATUS_WITHDRAWN,
                )
            )
        position = rank_end + 1
    return rows


def group_is_provisional(facts: StandingsFacts) -> bool:
    """该小组的排名是否 provisional（尚有未完成对抗）。

    规则文档 §8：**只要组内还有任何未完成的 TeamTie**（无论涉及 ACTIVE 还是 WITHDRAWN 队伍），
    排名都不是最终结果，`automatic_qualification_allowed` 必须为 false。
    V1 不做"结果可能性分析"（不判断某队是否已锁定出线）。
    """
    known = set(facts.team_entry_ids)
    for tie in facts.ties:
        if tie.status == TIE_STATUS_FINISHED and tie.winner_entry_id is not None:
            continue
        relevant = tie.entry_a_id in known or tie.entry_b_id in known
        if relevant:
            return True
    return False
