"""团体小组排名服务（A6.2）：读取真实事实 → 标准化 → 调 domain 纯算法 → 返回 DTO。

## 分工

- **repository**：只提供 SQL（对抗 + 各盘的状态/胜者/局分）。
- **domain/team_standings.py**：纯算法（比赛积分 2/1、子集重算、盘/局比率、并列区间）。
  规则源是 `docs/TEAM_GROUP_RULES_V1.md`。
- **本服务**：赛事 / 项目 / 小组归属校验，读取该组的 TeamEntry 与 GROUP 对抗，把数据库行
  标准化成事实对象，调用算法，组装小组级 DTO（provisional / qualify_count / 晋级事实）。
- **router**：只做参数解析与错误映射。

## 不持久化

每次查询都从真实 `team_ties` / `team_rubbers` 重新计算，**没有** `team_standings` 表，
因此不存在"排名缓存与事实不一致"的第二真相源；改分 / 补分 / 新完成的对抗天然整体重算。

## 不做的事（A6.2 范围）

不写入任何晋级结果、不做人工裁定 API、不做抽签、不做团体淘汰赛、不做排程/ETA、
不做 points ratio、不推进 `Tournament.stage`。
"""

import sqlite3

from .. import repository as repo
from ..domain import team_standings as domain
from ..models import EventType

#: `qualification_position_state` 的取值（事实描述，**不是**晋级结果）。
POSITION_RESOLVED = "RESOLVED"          # 名次已确定，且完全落在晋级线内
POSITION_UNDECIDED = "UNDECIDED"        # 排名未定（provisional / ambiguous）
POSITION_ELIGIBLE_ONLY = "ELIGIBLE_ONLY"  # 名次已确定但在晋级线外，或本身不可晋级

ENTRY_STATUS_WITHDRAWN = "WITHDRAWN"


class TeamStandingsError(Exception):
    def __init__(self, message: str, code: int = 404):
        super().__init__(message)
        self.code = code


def _tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TeamStandingsError("赛事不存在", 404)
    if tournament["event_type"] != EventType.TEAM.value:
        raise TeamStandingsError(
            f"当前赛事项目是 {tournament['event_type']}，只有团体赛（TEAM）有团体小组排名", 409
        )
    return tournament


def _group(conn: sqlite3.Connection, tournament_id: int, group_id: int) -> dict:
    group = repo.get_group(conn, group_id)
    if group is None or group["tournament_id"] != tournament_id:
        raise TeamStandingsError("小组不存在或不属于本赛事", 404)
    return group


def _facts(
    conn: sqlite3.Connection, tournament_id: int, group_id: int
) -> domain.StandingsFacts:
    """把该组的真实行标准化成域层事实（纯数据搬运，不含任何业务判断）。"""
    entries = [
        entry
        for entry in repo.list_entries_by_type(conn, tournament_id, EventType.TEAM.value)
        if entry["group_id"] == group_id
    ]
    # 稳定顺序：entries.id 升序（与 A6.1 生成器的顺序口径一致）。
    entries.sort(key=lambda entry: entry["id"])

    ties = repo.list_group_team_ties_with_rubbers(conn, tournament_id, group_id)
    return domain.StandingsFacts(
        entries=tuple(
            domain.TeamEntryFact(
                team_entry_id=entry["id"],
                team_name=entry["display_name"],
                status=entry["status"],
            )
            for entry in entries
        ),
        ties=tuple(
            domain.TeamTieFact(
                tie_id=tie["id"],
                entry_a_id=tie["entry_a_id"],
                entry_b_id=tie["entry_b_id"],
                status=tie["status"],
                winner_entry_id=tie["winner_entry_id"],
                rubbers=tuple(
                    domain.TeamRubberFact(
                        tie_id=tie["id"],
                        sequence=rubber["sequence"],
                        status=rubber["status"],
                        winner_entry_id=rubber["winner_entry_id"],
                        home_score=rubber["home_score"],
                        away_score=rubber["away_score"],
                    )
                    for rubber in tie["rubbers"]
                ),
            )
            for tie in ties
        ),
    )


def _position_state(row: domain.StandingRow, qualify_count: int, decided: bool) -> str:
    """名次相对于晋级线的**事实描述**（不推进晋级）。

    - 排名未定（provisional / 并列）→ UNDECIDED；
    - 名次已定且完全在晋级线内、且该队可晋级 → RESOLVED；
    - 其余（在晋级线外，或本身不可晋级）→ ELIGIBLE_ONLY。
    """
    if not decided or row.ambiguous:
        return POSITION_UNDECIDED
    if not row.eligible_for_qualification:
        return POSITION_ELIGIBLE_ONLY
    if row.rank_start >= 1 and row.rank_end <= qualify_count:
        return POSITION_RESOLVED
    return POSITION_ELIGIBLE_ONLY


def _build_group_standings(
    conn: sqlite3.Connection, tournament: dict, group: dict
) -> dict:
    facts = _facts(conn, tournament["id"], group["id"])
    rows = domain.compute_team_group_standings(facts)

    provisional = domain.group_is_provisional(facts)
    any_ambiguous = any(row.ambiguous for row in rows)
    # 与个人赛 `/rankings` 同一口径：组级覆盖值优先，否则用赛事默认值（不新增规则）。
    qualify_count = group["qualify_count"] or tournament["qualify_per_group"]

    return {
        "group_id": group["id"],
        "group_name": group["name"],
        "provisional": provisional,
        "ambiguous": any_ambiguous,
        # 只要还有未完成对抗（含涉及已退赛队伍的），就不允许自动晋级判定。
        "automatic_qualification_allowed": not provisional,
        "qualify_count": qualify_count,
        "standings": [
            {
                "team_entry_id": row.team_entry_id,
                "team_name": row.team_name,
                "status": row.status,
                "match_points": row.match_points,
                "ties_played": row.ties_played,
                "ties_won": row.ties_won,
                "ties_lost": row.ties_lost,
                "rubber_wins": row.rubber_wins,
                "rubber_losses": row.rubber_losses,
                "games_won": row.games_won,
                "games_lost": row.games_lost,
                "rank_start": row.rank_start,
                "rank_end": row.rank_end,
                "ambiguous": row.ambiguous,
                "eligible_for_qualification": row.eligible_for_qualification,
                "qualification_position_state": _position_state(
                    row, qualify_count, decided=not provisional
                ),
            }
            for row in rows
        ],
    }


def get_team_group_standings(
    conn: sqlite3.Connection, tournament_id: int, group_id: int
) -> dict:
    """单个小组的团体排名（比赛积分 → 子集重算 → 盘比率 → 局比率 → 并列区间）。"""
    tournament = _tournament(conn, tournament_id)
    group = _group(conn, tournament_id, group_id)
    return _build_group_standings(conn, tournament, group)


def list_team_group_standings(
    conn: sqlite3.Connection, tournament_id: int, group_id: int | None = None
) -> list[dict]:
    """本赛事全部（或指定）小组的团体排名，按 `groups.sort_order` 稳定排序。"""
    tournament = _tournament(conn, tournament_id)
    if group_id is None:
        groups = repo.list_groups(conn, tournament_id)
    else:
        groups = [_group(conn, tournament_id, group_id)]
    return [_build_group_standings(conn, tournament, group) for group in groups]


__all__ = [
    "ENTRY_STATUS_WITHDRAWN",
    "POSITION_ELIGIBLE_ONLY",
    "POSITION_RESOLVED",
    "POSITION_UNDECIDED",
    "TeamStandingsError",
    "get_team_group_standings",
    "list_team_group_standings",
]
