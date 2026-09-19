"""团体晋级服务（A6.3）：读 A6.2 排名事实 → 判定晋级 → 人工确认落库。

规则源：[`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`](../../../docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md)；
纯算法在 `domain/team_qualification.py`。

## 分工

- **domain/team_qualification.py**：纯判定（谁按名次晋级、哪里跨线并列、能否自动确认）。
- **本服务**：赛事/项目校验、调用 A6.2 取排名、把域层结论组装成 DTO、人工确认的校验与落库。
- **router**：只做参数解析与错误映射。

## 数据来源与真相

- **排名事实**：永远来自 `services/team_standings.py`（A6.2 每次现算），**不缓存、不复制**。
- **晋级结果**：`team_qualifications` 表，只存"哪些队伍被确认晋级"（人工确认的产物）。

## 并发

确认操作是"清空旧确认 → 写入新确认"，属于 read-check-write，
因此与其它团体赛写操作共用 `services/transaction.py::write_transaction`（`BEGIN IMMEDIATE`）：
写锁内重新读取排名并重新校验，两个并发确认只会一个成功。

**明确不做**（A6.3 范围外）：不实现状态机、不做撤销审计、不做抽签、
不做自动并列处理（并列必须人工确认，绝不按 id / 随机 / 顺序打破）。
"""

import sqlite3

from .. import repository as repo
from ..domain import team_qualification as domain
from ..domain.team_qualification import TeamQualificationError
from ..models import EventType
from . import team_standings as standings_service
from .transaction import TransactionBusyError, write_transaction

#: 本服务对外抛出的异常类型（router 直接映射 status_code）。
ServiceError = TeamQualificationError


def _tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise ServiceError("赛事不存在", 404)
    if tournament["event_type"] != EventType.TEAM.value:
        raise ServiceError(
            f"当前赛事项目是 {tournament['event_type']}，只有团体赛（TEAM）有团体晋级", 409
        )
    return tournament


def _group_facts(conn: sqlite3.Connection, tournament_id: int) -> list[domain.GroupStandingFact]:
    """把 A6.2 的排名结果标准化成域层事实（按 groups.sort_order）。"""
    payload = standings_service.list_team_group_standings(conn, tournament_id)
    return [
        domain.GroupStandingFact(
            group_id=group["group_id"],
            group_name=group["group_name"],
            qualify_count=group["qualify_count"],
            provisional=group["provisional"],
            standings=tuple(
                domain.StandingFact(
                    team_entry_id=row["team_entry_id"],
                    team_name=row["team_name"],
                    rank_start=row["rank_start"],
                    rank_end=row["rank_end"],
                    ambiguous=row["ambiguous"],
                    eligible_for_qualification=row["eligible_for_qualification"],
                    status=row["status"],
                )
                for row in group["standings"]
            ),
        )
        for group in payload
    ]


def _rank_index(conn: sqlite3.Connection, tournament_id: int, group_id: int) -> dict[int, int]:
    """队伍 → 在所属小组排名里的**展示序号**（从 1 起，仅用于稳定排序与展示）。

    注意：并列区间内的序号**不代表名次**；它只用来让输出顺序稳定可测。
    """
    payload = standings_service.get_team_group_standings(conn, tournament_id, group_id)
    return {
        row["team_entry_id"]: index
        for index, row in enumerate(payload["standings"], start=1)
    }


def _group_name_map(conn: sqlite3.Connection, tournament_id: int) -> dict[int, str]:
    return {group["id"]: group["name"] for group in repo.list_groups(conn, tournament_id)}


def _confirmed_rows(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """已确认的晋级队伍（按 小组顺序 → 组内排名展示序号 排序，稳定可测）。"""
    confirmed = repo.list_team_qualifications(conn, tournament_id)
    if not confirmed:
        return []
    group_order = {
        group["id"]: index for index, group in enumerate(repo.list_groups(conn, tournament_id))
    }
    order_within: dict[int, dict[int, int]] = {}
    for group_id in {row["group_id"] for row in confirmed if row["group_id"] is not None}:
        order_within[group_id] = _rank_index(conn, tournament_id, group_id)

    def sort_key(row: dict) -> tuple[int, int, int]:
        return (
            group_order.get(row["group_id"], len(group_order)),
            order_within.get(row["group_id"], {}).get(row["team_entry_id"], 0),
            row["team_entry_id"],
        )

    return sorted(confirmed, key=sort_key)


def _group_view(
    outcome_group: domain.GroupQualification,
    name_by_team: dict[int, str],
    confirmed_ids: set[int],
) -> dict:
    auto = set(outcome_group.auto_qualified)
    tied = set(outcome_group.boundary_tied_team_ids)
    return {
        "group_id": outcome_group.group_id,
        "group_name": outcome_group.group_name,
        "qualify_count": outcome_group.qualify_count,
        "provisional": outcome_group.provisional,
        "requires_manual_resolution": outcome_group.requires_manual_resolution,
        "can_confirm": outcome_group.can_confirm,
        "auto_qualified_team_ids": list(outcome_group.auto_qualified),
        "boundary_tied_team_ids": list(outcome_group.boundary_tied_team_ids),
        "boundary_slots_remaining": outcome_group.boundary_slots_remaining,
        "blocked_reasons": list(outcome_group.blocked_reasons),
        "confirmed_team_ids": [
            team_id for team_id in outcome_group.candidates if team_id in confirmed_ids
        ],
        "candidates": [
            {
                "team_entry_id": team_id,
                "team_name": name_by_team.get(team_id, str(team_id)),
                "auto_qualified": team_id in auto,
                "on_boundary_tie": team_id in tied,
            }
            for team_id in outcome_group.candidates
        ],
    }


def _name_map(conn: sqlite3.Connection, tournament_id: int) -> dict[int, str]:
    return {
        entry["id"]: entry["display_name"]
        for entry in repo.list_entries_by_type(conn, tournament_id, EventType.TEAM.value)
    }


def get_qualification(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """查询团体晋级状态（只读）。

    返回每组的候选、当前排名事实、是否需要人工处理、是否可以确认，
    以及已经确认过的晋级队伍（若有）。
    """
    _tournament(conn, tournament_id)
    facts = _group_facts(conn, tournament_id)
    outcome = domain.resolve_qualification(facts)
    names = _name_map(conn, tournament_id)
    confirmed = _confirmed_rows(conn, tournament_id)
    confirmed_ids = {row["team_entry_id"] for row in confirmed}
    group_names = _group_name_map(conn, tournament_id)

    return {
        "tournament_id": tournament_id,
        "provisional": outcome.provisional,
        "requires_manual_resolution": outcome.requires_manual_resolution,
        "can_confirm": outcome.can_confirm,
        "blocked_reasons": list(outcome.blocked_reasons),
        "groups": [
            _group_view(group, names, confirmed_ids) for group in outcome.groups
        ],
        "confirmed": [
            {
                "team_entry_id": row["team_entry_id"],
                "team_name": names.get(row["team_entry_id"], str(row["team_entry_id"])),
                "group_id": row["group_id"],
                "group_name": group_names.get(row["group_id"]),
                "status": row["status"],
                "confirmed_at": row["confirmed_at"],
            }
            for row in confirmed
        ],
    }


def confirm_qualification(
    conn: sqlite3.Connection, tournament_id: int, qualified_team_ids: list[int]
) -> dict:
    """人工确认晋级名单（全量替换已有确认，一个写事务）。

    校验（全部在写锁内基于**最新**排名重新执行）：

    1. 赛事存在且是 TEAM 项目；
    2. 每个小组的比赛必须已全部结束（非 provisional）；
    3. 不允许重复队伍；
    4. 每个小组必须恰好选出 `qualify_count` 支；
    5. 队伍必须属于本赛事、是该组的可晋级候选（名次在晋级线内或跨线并列）；
    6. 跨线并列时，从并列块选出的数量必须正好等于剩余席位（既不能少选也不能多选）；
    7. 已退赛（不可晋级）的队伍不能被确认。

    失败 → 整体回滚，原有确认保持原样。
    """
    _tournament(conn, tournament_id)

    try:
        with write_transaction(
            conn,
            busy_message="团体晋级正在被另一个请求处理，请稍后重试",
            conflict_message="确认团体晋级时写入冲突，请稍后重试",
        ):
            # 取到写锁后重新读取排名：这里的结论才是可以安全落库的依据。
            facts = _group_facts(conn, tournament_id)
            outcome = domain.resolve_qualification(facts)

            # 先做"队伍是否存在且属于本赛事"的预检，再谈数量/并列取舍：
            # 否则一个外部队伍会被报成"某组数量不对"，掩盖真正的错误原因。
            known_teams = set(_name_map(conn, tournament_id))
            unknown = [team_id for team_id in dict.fromkeys(qualified_team_ids)
                       if team_id not in known_teams]
            if unknown:
                raise ServiceError(f"队伍 {unknown[0]} 不存在或不属于本赛事", 404)

            selected = domain.validate_selection(outcome, qualified_team_ids)

            # 队伍 → 所属小组（用于落库时的 group_id）
            group_of_team: dict[int, int | None] = {}
            for group in facts:
                for row in group.standings:
                    group_of_team[row.team_entry_id] = group.group_id

            repo.delete_team_qualifications(conn, tournament_id)
            for team_id in selected:
                repo.create_team_qualification(
                    conn, tournament_id, team_id, group_of_team.get(team_id)
                )
    except TransactionBusyError as exc:
        raise ServiceError(str(exc), exc.code) from None

    return get_qualification(conn, tournament_id)
