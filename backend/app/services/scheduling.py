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


def match_ready(match: dict) -> bool:
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
    都只是"没有偏好"，调度时回退到"最落后的小组"。
    """
    tables = repo.list_tables(conn, tournament_id)
    if not tables:
        return {}
    groups = repo.list_groups(conn, tournament_id)
    return {
        group["id"]: tables[index % len(tables)]["id"]
        for index, group in enumerate(groups)
    }


# --------------------------------------------------------------- 调度排序依据

# 一次调度中最多回看"每组最近多少场已结束比赛"作为"刚打完"的代理。
# matches 表没有 finished_at；这里按 球台数/小组数 估算一批可能同时结束的场次，上限 3。
RECENT_FINISHED_MATCH_CAP = 3


def _group_progress(
    matches: list[dict], groups: list[dict]
) -> dict[int, dict]:
    """每个小组的调度进度：progress = (finished + playing) / total。

    已完成与进行中同等计入，因为已经在台上的比赛同样代表该组正在推进。
    真实排台与 ETA 模拟都通过状态快照复用本函数。
    """
    stats: dict[int, dict] = {}
    for group in groups:
        group_id = group["id"]
        group_matches = [m for m in matches if m["group_id"] == group_id]
        total = len(group_matches)
        finished = sum(1 for m in group_matches if m["status"] == MatchStatus.FINISHED.value)
        playing = sum(1 for m in group_matches if m["status"] == MatchStatus.PLAYING.value)
        stats[group_id] = {
            "total": total,
            "finished": finished,
            "playing": playing,
            "progress": (finished + playing) / total if total else 1.0,
            "order": group["sort_order"],
        }
    return stats


def _bump_group_progress(stats: dict[int, dict], group_id: int | None) -> None:
    """本批已给该组安排一场：立即计入进度，避免同一批把多余球台都塞给同一个组。"""
    entry = stats.get(group_id) if group_id is not None else None
    if entry is None or entry["total"] == 0:
        return
    entry["playing"] += 1
    entry["progress"] = (entry["finished"] + entry["playing"]) / entry["total"]


def _recent_window_size(free_table_count: int, group_count: int) -> int:
    """每组回看多少场"最近结束"的比赛（调度启发式参数，不是最短休息时间规则）。"""
    return min(
        RECENT_FINISHED_MATCH_CAP,
        max(1, -(-free_table_count // max(1, group_count))),
    )


def _recently_played_player_ids(state: dict, window: int) -> set[int]:
    """"刚打完"的选手集合（软惩罚，用于避免同一选手连续上场）。

    按各组最近完成的比赛排序，优先使用真实 finished_at（A2 时间基础），
    finished_at 缺失（旧数据 / 系统轮空）时退回比赛 id 顺序。
    窗口大小只是调度启发式参数，不代表已冻结的"最短休息时间"规则。
    """
    recent: set[int] = set()
    for bucket in state["recent_finished_by_group"].values():
        for match in bucket[:window]:
            recent.update(state["members_by_match"].get(match["id"], set()))
    return recent


def _fairness_key(
    match: dict,
    stats: dict[int, dict],
    recently_played: set[int],
    members_by_match: dict[int, set[int]],
) -> tuple:
    """候选比赛的排序键（越小越优先）：组进度 → 已结束场次 → 连续上场 → 稳定顺序。"""
    recent_penalty = 1 if members_by_match.get(match["id"], set()) & recently_played else 0
    group_stats = stats.get(match["group_id"]) if match["group_id"] is not None else None
    if group_stats is None:
        # 淘汰赛 / 排位赛没有小组进度：单独一档，按轮次与 id 稳定排序。
        return (1, 0.0, 0, recent_penalty, 0, match["round"], match["id"])
    return (
        0,
        group_stats["progress"],
        group_stats["finished"],
        recent_penalty,
        group_stats["order"],
        match["round"],
        match["id"],
    )


def build_plan_state(
    conn: sqlite3.Connection,
    tournament_id: int,
    *,
    matches: list[dict] | None = None,
    tables: list[dict] | None = None,
) -> dict:
    """排台状态快照：真实排台与 ETA 模拟共用同一份规则输入。

    快照内的 matches / tables 是可写副本，`plan_batch()` 只修改内存快照，
    绝不写数据库；因此 ETA 可以安全地反复模拟。
    """
    if matches is None:
        matches = repo.list_matches(conn, tournament_id)
    if tables is None:
        tables = repo.list_tables(conn, tournament_id)
    groups = repo.list_groups(conn, tournament_id)

    snapshot_matches = [dict(m) for m in matches]
    snapshot_tables = [dict(t) for t in tables]
    members_by_match: dict[int, set[int]] = {}
    for match in snapshot_matches:
        if match["status"] in (MatchStatus.WAITING.value, MatchStatus.PLAYING.value):
            members_by_match[match["id"]] = _match_member_ids(conn, match)

    recent_finished_by_group: dict[int | None, list[dict]] = {}
    for match in snapshot_matches:
        if match["status"] == MatchStatus.FINISHED.value:
            recent_finished_by_group.setdefault(match["group_id"], []).append(match)
    for bucket in recent_finished_by_group.values():
        # 真实 finished_at 优先；旧数据没有时间时按 id 兜底，保证确定性。
        bucket.sort(key=lambda m: (m.get("finished_at") or "", m["id"]), reverse=True)
        for match in bucket[:RECENT_FINISHED_MATCH_CAP]:
            members_by_match.setdefault(match["id"], _match_member_ids(conn, match))

    return {
        "matches": snapshot_matches,
        "tables": snapshot_tables,
        "groups": groups,
        "affinity": group_table_affinity(conn, tournament_id),
        "stats": _group_progress(snapshot_matches, groups),
        "members_by_match": members_by_match,
        "recent_finished_by_group": recent_finished_by_group,
    }


def plan_batch(state: dict) -> list[tuple[int, int]]:
    """按状态快照给当前空闲球台各排一场（纯内存，不写数据库）。

    优先级：
      1. 硬约束：只排 WAITING 且双方就绪、选手不在其他场次、球台空闲且不重复；
      2. 组台亲和：球台优先安排其对应小组的比赛；
      3. 组间进度公平：亲和组已经领先时，把球台让给最落后的小组；
      4. 连续上场惩罚：双方刚打完的比赛排在后面；
      5. 稳定顺序：小组顺序 → 轮次 → 比赛 id（全程无随机）。

    真实排台、dashboard 建议与 ETA 模拟都走本函数，避免两套规则漂移。
    """
    free_table_ids = [
        table["id"] for table in state["tables"]
        if table["status"] == TableStatus.FREE.value
    ]
    if not free_table_ids:
        return []

    matches = state["matches"]
    members_by_match = state["members_by_match"]
    stats = state["stats"]
    affinity = state["affinity"]
    busy: set[int] = set()
    for match in matches:
        if match["status"] == MatchStatus.PLAYING.value:
            busy.update(members_by_match.get(match["id"], set()))
    window = _recent_window_size(len(free_table_ids), len(stats))
    recently_played = _recently_played_player_ids(state, window)
    candidates = [
        match for match in matches
        if match["status"] == MatchStatus.WAITING.value
        and match_ready(match)
        and not (members_by_match.get(match["id"], set()) & busy)
    ]

    tables_by_id = {table["id"]: table for table in state["tables"]}
    assignments: list[tuple[int, int]] = []
    batch_busy = set(busy)
    used: set[int] = set()
    for table_id in free_table_ids:
        best_key: tuple | None = None
        best_match: dict | None = None
        affinity_key: tuple | None = None
        affinity_match: dict | None = None
        for match in candidates:
            if match["id"] in used or members_by_match.get(match["id"], set()) & batch_busy:
                continue
            key = _fairness_key(match, stats, recently_played, members_by_match)
            if best_key is None or key < best_key:
                best_key, best_match = key, match
            if affinity.get(match["group_id"]) == table_id:
                if affinity_key is None or key < affinity_key:
                    affinity_key, affinity_match = key, match
        if best_match is None or best_key is None:
            continue
        # 亲和只在"该组并不领先"时生效：领先的组把球台让给落后的小组。
        if affinity_match is not None and affinity_key is not None and affinity_key[:2] == best_key[:2]:
            chosen = affinity_match
        else:
            chosen = best_match
        assignments.append((chosen["id"], table_id))
        used.add(chosen["id"])
        batch_busy.update(members_by_match.get(chosen["id"], set()))
        _bump_group_progress(stats, chosen["group_id"])
        # 同步内存快照，供下一批（ETA 模拟）看到"已上台"的状态
        chosen["status"] = MatchStatus.PLAYING.value
        chosen["table_id"] = table_id
        tables_by_id[table_id]["status"] = TableStatus.OCCUPIED.value
    return assignments


def finish_match_in_state(state: dict, match_id: int) -> bool:
    """ETA 模拟专用：把状态快照里的一场比赛标记为已结束（不写数据库）。

    同时释放球台、更新小组进度，并把该场计入"最近完成"，使后续模拟批次的
    连续上场惩罚与进度公平与真实排台一致。
    """
    match = next((m for m in state["matches"] if m["id"] == match_id), None)
    if match is None or match["status"] != MatchStatus.PLAYING.value:
        return False
    match["status"] = MatchStatus.FINISHED.value
    table_id = match.get("table_id")
    for table in state["tables"]:
        if table["id"] == table_id:
            table["status"] = TableStatus.FREE.value
            break
    match["table_id"] = None
    stats = state["stats"].get(match["group_id"]) if match["group_id"] is not None else None
    if stats is not None and stats["total"]:
        stats["playing"] = max(0, stats["playing"] - 1)
        stats["finished"] += 1
        stats["progress"] = (stats["finished"] + stats["playing"]) / stats["total"]
    bucket = state["recent_finished_by_group"].setdefault(match["group_id"], [])
    bucket.insert(0, match)
    del bucket[RECENT_FINISHED_MATCH_CAP:]
    return True


def _plan_assignments(
    conn: sqlite3.Connection, tournament_id: int
) -> tuple[list[tuple[int, int]], dict[int, int]]:
    """只读规划：返回 ([(match_id, table_id)], {table_id: recommended_match_id})。

    优先级与 `plan_batch` 一致；本函数只读库，不修改任何比赛或球台状态。
    """
    _ensure_tournament(conn, tournament_id)
    state = build_plan_state(conn, tournament_id)
    assignments = plan_batch(state)
    recommendations = {table_id: match_id for match_id, table_id in assignments}
    return assignments, recommendations


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
    if not match_ready(match):
        raise SchedulingError("比赛双方选手尚未就绪，不能上球台")
    if table["status"] != TableStatus.FREE.value:
        raise SchedulingError("球台已被占用")

    busy = _busy_player_ids(conn, match["tournament_id"])
    if _match_member_ids(conn, match) & busy:
        raise SchedulingError("选手正在参加其他比赛，不能同时上场")

    # 上台即写 called_at / started_at（UTC），手工排台与自动排台走同一 helper。
    repo.mark_match_playing(conn, match_id, table_id)
    repo.update_table_status(conn, table_id, TableStatus.OCCUPIED.value)
    conn.commit()
    return repo.get_match(conn, match_id)


def schedule_next(conn: sqlite3.Connection, tournament_id: int) -> list[tuple[int, int]]:
    """贪心批量调度：每张空闲球台按"亲和 + 公平"安排一场比赛。

    优先级见 `_plan_assignments`：硬约束 → 组台亲和 → 组间进度公平 →
    连续上场惩罚 → 稳定顺序。组台亲和是软约束：当对应小组已经领先时，
    球台会让给更落后的小组，避免 table_count < group_count 时后面的组长期不开赛。
    """
    assignments, _ = _plan_assignments(conn, tournament_id)
    for match_id, table_id in assignments:
        # 自动排台与手工排台共用同一 helper，保证 called_at / started_at 不会一边有一边没有。
        repo.mark_match_playing(conn, match_id, table_id)
        repo.update_table_status(conn, table_id, TableStatus.OCCUPIED.value)
    conn.commit()
    return assignments


def release_match(conn: sqlite3.Connection, match_id: int) -> dict:
    """把一场 PLAYING 比赛下球台（回到 WAITING，释放球台）。

    时间语义：本次上台不构成有效的进行中比赛，started_at 置空；
    called_at 保留"最近一次叫号"的事实，重新安排时刷新。
    """
    match = _ensure_match(conn, match_id)
    if match["status"] != MatchStatus.PLAYING.value:
        raise SchedulingError("只有进行中的比赛可以下球台")
    if match["table_id"] is not None:
        repo.update_table_status(conn, match["table_id"], TableStatus.FREE.value)
    repo.mark_match_waiting(conn, match_id)
    conn.commit()
    return repo.get_match(conn, match_id)


def get_dashboard(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """控制台聚合数据：进度统计 + 每台当前比赛 + 建议安排 + 下一批可执行比赛。

    空闲球台附带 `recommended_match_id`（由调度器同一套规则算出），
    前端只展示建议、不自行重算优先级。
    """
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

    _, recommended = _plan_assignments(conn, tournament_id)
    tables = []
    for t in repo.list_tables(conn, tournament_id):
        tables.append(
            {
                "id": t["id"],
                "name": t["name"],
                "status": t["status"],
                "recommended_match_id": recommended.get(t["id"]),
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
        and match_ready(m)
        and not (_match_member_ids(conn, m) & busy)
    ]

    return {
        "tournament": repo.get_tournament(conn, tournament_id),
        "stats": stats,
        "tables": tables,
        "next_playable": [repo.decorate_match(conn, m) for m in next_playable],
    }
