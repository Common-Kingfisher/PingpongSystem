"""团体晋级判定（A6.3）——纯函数，不访问数据库。

规则源：[`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`](../../../docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md)。

## 输入是 A6.2 的排名事实

调用方（`services/team_qualification.py`）把 `TeamGroupStandingsOut` 标准化成
`GroupStandingFact` 列表；本模块只做纯计算，输出每个小组的晋级结论。

## 规则（V1）

每个小组按 `groups.qualify_count`（为空时回退赛事 `qualify_per_group`）取前 N 名：

- **名次区间完全落在晋级线内**（`rank_end <= qualify_count`）→ 直接晋级；
- **名次区间完全在晋级线外**（`rank_start > qualify_count`）→ 不晋级；
- **名次区间跨越晋级线**（`rank_start <= qualify_count < rank_end`）→ **存在并列**，
  该小组 `requires_manual_resolution = true`，**绝不**用任何 id / 顺序 / 随机方式打破并列。

## 硬性前置（不满足则禁止自动确认，也禁止生成淘汰签）

1. 排名 `provisional`（组内还有未完成的对抗）→ 不能确认；
2. `eligible_for_qualification == False`（已退赛）→ 不能晋级，也不能确认。

这两条同样是"事实未定"，不是并列问题，因此结论里用 `blocked_reasons` 明确列出，
让调用方给出可读错误，而不是让上层自己猜。
"""

from dataclasses import dataclass, field

from .team_standings import ENTRY_STATUS_WITHDRAWN


class TeamQualificationError(Exception):
    """晋级判定输入本身不合法，或人工确认名单不合法。

    `code` 默认 409（业务冲突）；名单层面的校验用 422（请求结构合法但取值不被接受），
    与仓库其它接口的错误码口径一致。
    """

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StandingFact:
    """一支队伍在所属小组排名中的**事实**（来自 A6.2）。"""

    team_entry_id: int
    team_name: str
    rank_start: int
    rank_end: int
    ambiguous: bool
    eligible_for_qualification: bool
    status: str = "ACTIVE"


@dataclass(frozen=True)
class GroupStandingFact:
    """一个小组的排名事实 + 该组的晋级名额。"""

    group_id: int
    group_name: str
    qualify_count: int
    #: 组内是否还有未完成对抗（A6.2 的 provisional）。
    provisional: bool
    standings: tuple[StandingFact, ...]


@dataclass
class GroupQualification:
    """一个小组的晋级结论。"""

    group_id: int
    group_name: str
    qualify_count: int
    provisional: bool
    #: 名次已确定、且完全落在晋级线内（不含并列待定）。
    auto_qualified: list[int] = field(default_factory=list)
    #: 跨晋级线并列、需要人工决定的队伍（按 A6.2 的稳定展示顺序）。
    boundary_tied_team_ids: list[int] = field(default_factory=list)
    #: 其中还剩几个晋级席位没有被自动填充。
    boundary_slots_remaining: int = 0
    #: 该组是否需要人工确认（存在跨晋级线并列）。
    requires_manual_resolution: bool = False
    #: 该组是否**可以由系统直接确认**（无并列、非 provisional、可晋级队伍足够）。
    can_confirm: bool = False
    #: 该组可以参与晋级的候选队伍（名次在前 N 或跨线并列，且可晋级）。
    candidates: list[int] = field(default_factory=list)
    #: 阻止自动确认的原因（可读，供上层转成 409）。
    blocked_reasons: list[str] = field(default_factory=list)


@dataclass
class QualificationOutcome:
    """整个赛事的晋级判定结论。"""

    groups: list[GroupQualification]
    #: 任何一组 provisional → 整体不能确认。
    provisional: bool
    #: 任何一组存在跨晋级线并列 → 整体需要人工确认。
    requires_manual_resolution: bool
    #: 是否允许"系统直接确认"（全部组都非 provisional、无并列、且无其它阻塞）。
    can_confirm: bool
    blocked_reasons: list[str] = field(default_factory=list)


def _validate(group: GroupStandingFact) -> None:
    if group.qualify_count < 1:
        raise TeamQualificationError(f"{group.group_name} 的晋级名额必须是正整数")
    if not group.standings:
        raise TeamQualificationError(f"{group.group_name} 没有排名数据，不能判定晋级")
    if len(group.standings) < group.qualify_count:
        raise TeamQualificationError(
            f"{group.group_name} 只有 {len(group.standings)} 支队伍，"
            f"少于晋级名额 {group.qualify_count}"
        )
    seen: set[int] = set()
    for row in group.standings:
        if row.team_entry_id in seen:
            raise TeamQualificationError(f"{group.group_name} 的排名里出现了重复队伍")
        seen.add(row.team_entry_id)
        if row.rank_start < 1 or row.rank_end < row.rank_start:
            raise TeamQualificationError(f"{group.group_name} 的名次区间不合法")
        if row.ambiguous != (row.rank_start != row.rank_end):
            raise TeamQualificationError(
                f"{group.group_name} 的名次区间与并列标记不一致"
                f"（{row.rank_start}-{row.rank_end}, ambiguous={row.ambiguous}）"
            )


def _ineligible(row: StandingFact) -> bool:
    return not row.eligible_for_qualification or row.status == ENTRY_STATUS_WITHDRAWN


def resolve_group(group: GroupStandingFact) -> GroupQualification:
    """判定一个小组的晋级结论。"""
    _validate(group)
    result = GroupQualification(
        group_id=group.group_id,
        group_name=group.group_name,
        qualify_count=group.qualify_count,
        provisional=group.provisional,
    )

    # 名次行按 A6.2 的稳定展示顺序处理；并列区间内的先后**不代表名次**，
    # 因此这里只依据 rank_start / rank_end 判断是否跨线，绝不按顺序选人。
    for row in group.standings:
        inside = row.rank_end <= group.qualify_count
        outside = row.rank_start > group.qualify_count
        if _ineligible(row):
            # 已退赛：不进入候选，也不构成"可晋级"的并列。
            continue
        if inside:
            result.auto_qualified.append(row.team_entry_id)
            result.candidates.append(row.team_entry_id)
        elif outside:
            continue
        else:
            # 跨晋级线并列：整块并列队伍都无法由系统决定。
            result.boundary_tied_team_ids.append(row.team_entry_id)
            result.candidates.append(row.team_entry_id)

    if result.boundary_tied_team_ids:
        result.requires_manual_resolution = True
        filled = len(result.auto_qualified)
        result.boundary_slots_remaining = group.qualify_count - filled

    if group.provisional:
        result.blocked_reasons.append(f"{group.group_name} 的比赛尚未全部结束，排名不是最终结果")
    if result.requires_manual_resolution and result.boundary_slots_remaining <= 0:
        # 理论上不会发生（跨线并列必然意味着席位没填满），保守处理为需要人工。
        result.blocked_reasons.append(f"{group.group_name} 的并列晋级席位无法自动确定")

    result.can_confirm = not result.blocked_reasons and not result.requires_manual_resolution
    return result


def resolve_qualification(
    groups: list[GroupStandingFact],
) -> QualificationOutcome:
    """判定整个赛事的晋级结论（按传入的小组顺序）。"""
    if not groups:
        raise TeamQualificationError("赛事还没有小组，不能判定晋级")

    resolved = [resolve_group(group) for group in groups]
    blocked: list[str] = []
    for group in resolved:
        for reason in group.blocked_reasons:
            if reason not in blocked:
                blocked.append(reason)

    return QualificationOutcome(
        groups=resolved,
        provisional=any(group.provisional for group in resolved),
        requires_manual_resolution=any(
            group.requires_manual_resolution for group in resolved
        ),
        can_confirm=not blocked and not any(
            group.requires_manual_resolution for group in resolved
        ),
        blocked_reasons=blocked,
    )


def validate_selection(
    outcome: QualificationOutcome, selected_team_ids: list[int]
) -> list[int]:
    """校验人工确认的晋级名单（返回去重后的稳定顺序）。

    校验项：
    1. 不允许重复队伍；
    2. 每个小组必须恰好选出 `qualify_count` 支；
    3. 选出的队伍必须在该组的**候选**里（即在晋级线内或跨线并列，且可晋级）；
    4. 跨线并列时，从并列块里选出的数量必须正好等于剩余席位
       （既不能少选——那会留下空席位，也不能多选——那会挤掉已确定晋级的队伍）。
    """
    if not selected_team_ids:
        raise TeamQualificationError("请提供晋级队伍", 422)
    if len(set(selected_team_ids)) != len(selected_team_ids):
        raise TeamQualificationError("晋级名单中存在重复队伍", 422)

    remaining = list(selected_team_ids)
    for group in outcome.groups:
        if group.provisional:
            raise TeamQualificationError(
                f"{group.group_name} 的比赛尚未全部结束，不能确认晋级", 409
            )
        candidates = set(group.candidates)
        tied = set(group.boundary_tied_team_ids)
        picked = [team_id for team_id in remaining if team_id in candidates]
        remaining = [team_id for team_id in remaining if team_id not in candidates]

        if len(picked) != group.qualify_count:
            raise TeamQualificationError(
                f"{group.group_name} 必须选出 {group.qualify_count} 支晋级队伍"
                f"（当前 {len(picked)} 支）",
                422,
            )
        if group.requires_manual_resolution:
            from_tie = [team_id for team_id in picked if team_id in tied]
            if len(from_tie) != group.boundary_slots_remaining:
                raise TeamQualificationError(
                    f"{group.group_name} 在晋级线上有并列：必须从并列的 "
                    f"{len(group.boundary_tied_team_ids)} 支队伍中选出 "
                    f"{group.boundary_slots_remaining} 支",
                    422,
                )

    if remaining:
        raise TeamQualificationError(
            "晋级名单包含不属于本赛事晋级候选的队伍", 422
        )
    return list(dict.fromkeys(selected_team_ids))
