"""比赛状态与球台调度服务。

状态机（本任务范围）：
  WAITING --assign-table/schedule-next--> PLAYING（球台 OCCUPIED）
  PLAYING --release--> WAITING（球台 FREE）
  PLAYING --录入比分(任务5)--> FINISHED（球台 FREE）

一致性不变量（本层强制，测试守护）：
  1. 同一名选手不同时处于两场 PLAYING；
  2. 同一张球台只承载一场 PLAYING；
  3. 只有 WAITING 比赛可以上球台；FINISHED 比赛不可再安排；
  4. PLAYING 比赛数 == OCCUPIED 球台数。
"""

import sqlite3

from .. import repository as repo
from ..domain import scheduler
from ..models import MatchStatus, TableStatus


class SchedulingError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _ensure_match(conn: sqlite3.Connection, match_id: int) -> dict:
    match = repo.get_match(conn, match_id)
    if match is None:
        raise SchedulingError("比赛不存在", 404)
    return match


def _ensure_tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise SchedulingError("赛事不存在", 404)
    return tournament


def _match_member_ids(conn: sqlite3.Connection, match: dict) -> set[int]:
    ids: set[int] = set()
    if match.get("entry_a_id") is not None and match.get("entry_b_id") is not None:
        for entry_id in (match["entry_a_id"], match["entry_b_id"]):
            ids.update(m["player_id"] for m in repo.list_entry_members(conn, entry_id))
    else:
        for player_id in (match.get("player_a_id"), match.get("player_b_id")):
            if player_id is not None:
                ids.add(player_id)
    return ids


def _match_ready(match: dict) -> bool:
    return (
        match.get("entry_a_id") is not None and match.get("entry_b_id") is not None
    ) or (
        match.get("player_a_id") is not None and match.get("player_b_id") is not None
    )


def _busy_player_ids(conn: sqlite3.Connection, tournament_id: int) -> set[int]:
    busy: set[int] = set()
    for m in repo.list_playing_matches(conn, tournament_id):
        busy.update(_match_member_ids(conn, m))
    return busy


def group_table_affinity(conn: sqlite3.Connection, tournament_id: int) -> dict[int, int]:
    """group_id → 首选球台 id（软约束）。

    按小组顺序（sort_order）与球台顺序（id）一一对应：第 1 组用第 1 张台……
    小组数多于球台数时按球台数取模复用；多于球台的小组、以及没有对应小组的球台，
    都只是"没有偏好"，调度时回退到任意可执行比赛。
    """
    tables = repo.list_tables(conn, tournament_id)
    if not tables:
        return {}
    groups = repo.list_groups(conn, tournament_id)
    return {
        group["id"]: tables[index % len(tables)]["id"]
        for index, group in enumerate(groups)
    }


def assign_table(conn: sqlite3.Connection, match_id: int, table_id: int) -> dict:
    """把一场 WAITING 比赛安排到指定空闲球台 → PLAYING。"""
    match = _ensure_match(conn, match_id)
    table = repo.get_table(conn, table_id)
    if table is None:
        raise SchedulingError("球台不存在", 404)
    if table["tournament_id"] != match["tournament_id"]:
        raise SchedulingError("球台不属于该赛事")
    if match["status"] != MatchStatus.WAITING.value:
        raise SchedulingError("只有待安排的比赛可以上球台")
    if not _match_ready(match):
        raise SchedulingError("比赛双方选手尚未就绪，不能上球台")
    if table["status"] != TableStatus.FREE.value:
        raise SchedulingError("球台已被占用")

    busy = _busy_player_ids(conn, match["tournament_id"])
    if _match_member_ids(conn, match) & busy:
        raise SchedulingError("选手正在参加其他比赛，不能同时上场")

    repo.update_match(conn, match_id, status=MatchStatus.PLAYING.value, table_id=table_id)
    repo.update_table_status(conn, table_id, TableStatus.OCCUPIED.value)
    conn.commit()
    return repo.get_match(conn, match_id)


def schedule_next(conn: sqlite3.Connection, tournament_id: int) -> list[tuple[int, int]]:
    """贪心批量调度：每张空闲球台优先安排其对应小组的待赛比赛。

    软约束（group-table affinity）：按 `group_table_affinity` 的对应关系，
    先尝试该球台"专属小组"的比赛；该小组当前没有可执行比赛时，回退到任意可执行比赛。
    硬约束（选手不冲突、球台不重复、只排 WAITING）保持不变。
    """
    _ensure_tournament(conn, tournament_id)
    free_tables = [
        t for t in repo.list_tables(conn, tournament_id)
        if t["status"] == TableStatus.FREE.value
    ]
    if not free_tables:
        return []

    busy = _busy_player_ids(conn, tournament_id)
    waiting = [
        m for m in repo.list_matches(conn, tournament_id)
        if m["status"] == MatchStatus.WAITING.value and _match_ready(m)
    ]
    members_by_match = {m["id"]: _match_member_ids(conn, m) for m in waiting}
    candidates = [m for m in waiting if not (members_by_match[m["id"]] & busy)]
    affinity = group_table_affinity(conn, tournament_id)

    assignments: list[tuple[int, int]] = []
    batch_busy = set(busy)
    used: set[int] = set()
    for table in free_tables:
        chosen: dict | None = None
        fallback: dict | None = None
        for match in candidates:
            if match["id"] in used or members_by_match[match["id"]] & batch_busy:
                continue
            if affinity.get(match["group_id"]) == table["id"]:
                chosen = match
                break
            if fallback is None:
                fallback = match
        if chosen is None:
            chosen = fallback
        if chosen is None:
            continue
        assignments.append((chosen["id"], table["id"]))
        used.add(chosen["id"])
        batch_busy.update(members_by_match[chosen["id"]])

    for match_id, table_id in assignments:
        repo.update_match(conn, match_id, status=MatchStatus.PLAYING.value, table_id=table_id)
        repo.update_table_status(conn, table_id, TableStatus.OCCUPIED.value)
    conn.commit()
    return assignments


def release_match(conn: sqlite3.Connection, match_id: int) -> dict:
    """把一场 PLAYING 比赛下球台（回到 WAITING，释放球台）。"""
    match = _ensure_match(conn, match_id)
    if match["status"] != MatchStatus.PLAYING.value:
        raise SchedulingError("只有进行中的比赛可以下球台")
    if match["table_id"] is not None:
        repo.update_table_status(conn, match["table_id"], TableStatus.FREE.value)
    repo.update_match(conn, match_id, status=MatchStatus.WAITING.value, table_id=None)
    conn.commit()
    return repo.get_match(conn, match_id)


def get_dashboard(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """控制台聚合数据：进度统计 + 每台当前比赛 + 下一批可执行比赛。"""
    _ensure_tournament(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id)
    stats = {
        "total": len(matches),
        "finished": sum(1 for m in matches if m["status"] == MatchStatus.FINISHED.value),
        "playing": sum(1 for m in matches if m["status"] == MatchStatus.PLAYING.value),
        "waiting": sum(1 for m in matches if m["status"] == MatchStatus.WAITING.value),
    }
    playing = [m for m in matches if m["status"] == MatchStatus.PLAYING.value]
    playing_by_table = {m["table_id"]: m for m in playing}

    tables = []
    for t in repo.list_tables(conn, tournament_id):
        tables.append(
            {
                "id": t["id"],
                "name": t["name"],
                "status": t["status"],
                "match": (
                    repo.decorate_match(conn, playing_by_table[t["id"]])
                    if t["id"] in playing_by_table else None
                ),
            }
        )

    busy = set()
    for m in playing:
        busy.update(_match_member_ids(conn, m))
    next_playable = [
        m for m in matches
        if m["status"] == MatchStatus.WAITING.value
        and _match_ready(m)
        and not (_match_member_ids(conn, m) & busy)
    ]

    return {
        "tournament": repo.get_tournament(conn, tournament_id),
        "stats": stats,
        "tables": tables,
        "next_playable": [repo.decorate_match(conn, m) for m in next_playable],
    }
