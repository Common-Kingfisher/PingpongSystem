"""SQL 访问层（repository）。

所有 SQL 集中在这里。函数接收 sqlite3.Connection，返回 dict 或 dict 列表。
业务规则（哪些操作被禁止等）不放在本层，放在 services/ 或 domain/。
"""

import sqlite3
from typing import Any, Optional

from .models import TableStatus

# ---------------------------------------------------------------- tournaments

_TOURNAMENT_COLS = (
    "id, name, date, table_count, group_count, qualify_per_group, stage, created_at, "
    "event_type, bronze_mode, placement_mode, games_to_win, points_to_win, "
    "roster_confirmed, confirmed_at, operation_mode, owner_user_id"
)


def create_tournament(
    conn: sqlite3.Connection,
    name: str,
    date: str,
    table_count: int,
    group_count: int,
    qualify_per_group: int,
    event_type: str = "SINGLES",
    bronze_mode: str = "JOINT_BRONZE",
    placement_mode: str = "OFF",
    games_to_win: int = 2,
    points_to_win: int = 11,
    operation_mode: str = "LIVE",
    owner_user_id: int | None = None,
) -> dict:
    cur = conn.execute(
        "INSERT INTO tournaments (name, date, table_count, group_count, qualify_per_group, "
        "event_type, bronze_mode, placement_mode, games_to_win, points_to_win, operation_mode, "
        "owner_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, date, table_count, group_count, qualify_per_group, event_type,
         bronze_mode, placement_mode, games_to_win, points_to_win, operation_mode,
         owner_user_id),
    )
    row = conn.execute(
        f"SELECT {_TOURNAMENT_COLS} FROM tournaments WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def get_tournament(conn: sqlite3.Connection, tournament_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_TOURNAMENT_COLS} FROM tournaments WHERE id = ?", (tournament_id,)
    ).fetchone()
    return dict(row) if row else None


def list_tournaments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_TOURNAMENT_COLS} FROM tournaments ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def update_tournament_stage(conn: sqlite3.Connection, tournament_id: int, stage: str) -> None:
    conn.execute(
        "UPDATE tournaments SET stage = ? WHERE id = ?", (stage, tournament_id)
    )


def confirm_tournament_roster(conn: sqlite3.Connection, tournament_id: int) -> None:
    conn.execute(
        "UPDATE tournaments SET roster_confirmed = 1, confirmed_at = datetime('now') WHERE id = ?",
        (tournament_id,),
    )


def unconfirm_tournament_roster(conn: sqlite3.Connection, tournament_id: int) -> None:
    conn.execute(
        "UPDATE tournaments SET roster_confirmed = 0, confirmed_at = NULL WHERE id = ?",
        (tournament_id,),
    )


def delete_tournament(conn: sqlite3.Connection, tournament_id: int) -> bool:
    """删除赛事（级联清理选手/球台/比赛/分组）。"""
    cur = conn.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
    return cur.rowcount > 0


# ------------------------------------------------------------------ tables

def create_tables_for_tournament(
    conn: sqlite3.Connection, tournament_id: int, count: int
) -> list[dict]:
    """创建 count 张球台，名称从 1号台 起。"""
    for i in range(1, count + 1):
        conn.execute(
            "INSERT INTO tables (tournament_id, name) VALUES (?, ?)",
            (tournament_id, f"{i}号台"),
        )
    return list_tables(conn, tournament_id)


def list_tables(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, tournament_id, name, status FROM tables WHERE tournament_id = ? ORDER BY id",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_table(conn: sqlite3.Connection, table_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, tournament_id, name, status FROM tables WHERE id = ?", (table_id,)
    ).fetchone()
    return dict(row) if row else None


def update_table_status(conn: sqlite3.Connection, table_id: int, status: str) -> None:
    conn.execute("UPDATE tables SET status = ? WHERE id = ?", (status, table_id))


# ------------------------------------------------------------------ players

_PLAYER_COLS = "id, tournament_id, name, college, group_id, seed_no, rating_points"


def add_player(
    conn: sqlite3.Connection,
    tournament_id: int,
    name: str,
    college: Optional[str],
    rating_points: int = 1000,
) -> dict:
    cur = conn.execute(
        "INSERT INTO players (tournament_id, name, college, rating_points) VALUES (?, ?, ?, ?)",
        (tournament_id, name, college, rating_points),
    )
    row = conn.execute(
        f"SELECT {_PLAYER_COLS} FROM players WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def get_player(conn: sqlite3.Connection, player_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_PLAYER_COLS} FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    return dict(row) if row else None


def list_players(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_PLAYER_COLS} FROM players WHERE tournament_id = ? ORDER BY id",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_player(
    conn: sqlite3.Connection,
    player_id: int,
    name: Optional[str],
    college: Optional[str],
    rating_points: Optional[int] = None,
) -> Optional[dict]:
    """按给定字段更新；college 传 None 且原值存在时置空。返回更新后的选手。"""
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if college is not None:
        sets.append("college = ?")
        params.append(college)
    if rating_points is not None:
        sets.append("rating_points = ?")
        params.append(rating_points)
    if sets:
        params.append(player_id)
        conn.execute(f"UPDATE players SET {', '.join(sets)} WHERE id = ?", params)
    return get_player(conn, player_id)


def replace_player_values(
    conn: sqlite3.Connection,
    player_id: int,
    name: str,
    college: Optional[str],
    rating_points: int,
) -> dict:
    conn.execute(
        "UPDATE players SET name = ?, college = ?, rating_points = ? WHERE id = ?",
        (name, college, rating_points, player_id),
    )
    return get_player(conn, player_id)


def delete_player(conn: sqlite3.Connection, player_id: int) -> bool:
    cur = conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    return cur.rowcount > 0


def clear_tournament_seeds(conn: sqlite3.Connection, tournament_id: int) -> None:
    """清空某赛事所有选手的种子序号。"""
    conn.execute("UPDATE players SET seed_no = NULL WHERE tournament_id = ?", (tournament_id,))


def set_player_seed(conn: sqlite3.Connection, player_id: int, seed_no: int) -> None:
    conn.execute("UPDATE players SET seed_no = ? WHERE id = ?", (seed_no, player_id))


# ------------------------------------------------------------------ entries

_ENTRY_COLS = (
    "id, tournament_id, entry_type, display_name, rating_points, sort_order, group_id, seed_no, status, "
    "withdrawn_at, withdrawn_by, withdrawal_reason"
)


def clear_entries(conn: sqlite3.Connection, tournament_id: int) -> None:
    conn.execute("DELETE FROM entries WHERE tournament_id = ?", (tournament_id,))


def create_entry(
    conn: sqlite3.Connection,
    tournament_id: int,
    entry_type: str,
    display_name: str,
    rating_points: int,
    member_ids: list[int],
    seed_no: int | None = None,
) -> dict:
    cur = conn.execute(
        "INSERT INTO entries (tournament_id, entry_type, display_name, rating_points, seed_no, sort_order) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (tournament_id, entry_type, display_name, rating_points, seed_no),
    )
    entry_id = int(cur.lastrowid)
    conn.execute("UPDATE entries SET sort_order = ? WHERE id = ?", (entry_id, entry_id))
    for order, player_id in enumerate(member_ids, start=1):
        conn.execute(
            "INSERT INTO entry_members (entry_id, player_id, member_order) VALUES (?, ?, ?)",
            (entry_id, player_id, order),
        )
    return get_entry(conn, entry_id)


def get_entry(conn: sqlite3.Connection, entry_id: int) -> Optional[dict]:
    row = conn.execute(f"SELECT {_ENTRY_COLS} FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return None
    entry = dict(row)
    entry["members"] = list_entry_members(conn, entry_id)
    return entry


def list_entry_members(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT p.id AS player_id, p.name, p.college, p.rating_points, em.member_order "
        "FROM entry_members em JOIN players p ON p.id = em.player_id "
        "WHERE em.entry_id = ? ORDER BY em.member_order",
        (entry_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_entries(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_ENTRY_COLS} FROM entries WHERE tournament_id = ? ORDER BY sort_order, id",
        (tournament_id,),
    ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["members"] = list_entry_members(conn, entry["id"])
        result.append(entry)
    return result


def set_entry_seed(conn: sqlite3.Connection, entry_id: int, seed_no: int | None) -> None:
    conn.execute("UPDATE entries SET seed_no = ? WHERE id = ?", (seed_no, entry_id))


def clear_entry_groups(conn: sqlite3.Connection, tournament_id: int) -> None:
    conn.execute("UPDATE entries SET group_id = NULL WHERE tournament_id = ?", (tournament_id,))


def set_entry_group(conn: sqlite3.Connection, entry_id: int, group_id: int) -> None:
    conn.execute("UPDATE entries SET group_id = ? WHERE id = ?", (group_id, entry_id))


def list_entries_by_type(
    conn: sqlite3.Connection, tournament_id: int, entry_type: str
) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_ENTRY_COLS} FROM entries WHERE tournament_id = ? AND entry_type = ? ORDER BY sort_order, id",
        (tournament_id, entry_type),
    ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["members"] = list_entry_members(conn, entry["id"])
        result.append(entry)
    return result


def withdraw_entry(
    conn: sqlite3.Connection, entry_id: int, operator_name: str, reason: str
) -> dict:
    conn.execute(
        "UPDATE entries SET status = 'WITHDRAWN', withdrawn_at = datetime('now'), "
        "withdrawn_by = ?, withdrawal_reason = ? WHERE id = ?",
        (operator_name, reason, entry_id),
    )
    return get_entry(conn, entry_id)


def update_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    display_name: str,
    rating_points: int,
) -> Optional[dict]:
    conn.execute(
        "UPDATE entries SET display_name = ?, rating_points = ? WHERE id = ?",
        (display_name, rating_points, entry_id),
    )
    return get_entry(conn, entry_id)


def update_entry_sort_order(conn: sqlite3.Connection, entry_id: int, sort_order: int) -> None:
    conn.execute("UPDATE entries SET sort_order = ? WHERE id = ?", (sort_order, entry_id))


def replace_entry_members(
    conn: sqlite3.Connection, entry_id: int, member_ids: list[int]
) -> Optional[dict]:
    """整表替换某 Entry 的成员（member_order 按传入顺序）。"""
    conn.execute("DELETE FROM entry_members WHERE entry_id = ?", (entry_id,))
    for order, player_id in enumerate(member_ids, start=1):
        conn.execute(
            "INSERT INTO entry_members (entry_id, player_id, member_order) VALUES (?, ?, ?)",
            (entry_id, player_id, order),
        )
    return get_entry(conn, entry_id)


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> bool:
    cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    return cur.rowcount > 0


def find_entry_of_player(
    conn: sqlite3.Connection,
    tournament_id: int,
    player_id: int,
    exclude_entry_id: Optional[int] = None,
) -> Optional[dict]:
    """查某选手当前挂在哪个 Entry 上（entry_members 对 player_id 全局唯一）。

    用于在触发 UNIQUE 约束前给出可读的业务错误，而不是抛 IntegrityError。
    """
    row = conn.execute(
        "SELECT e.id, e.entry_type, e.display_name FROM entry_members em "
        "JOIN entries e ON e.id = em.entry_id "
        "WHERE em.player_id = ? AND e.tournament_id = ? "
        "AND (? IS NULL OR e.id != ?) LIMIT 1",
        (player_id, tournament_id, exclude_entry_id, exclude_entry_id),
    ).fetchone()
    return dict(row) if row else None


# -------------------------------------------------- 团体赛（A3：TeamTie / TeamRubber）

_TIE_COLS = (
    "id, tournament_id, stage, group_id, round, match_index, entry_a_id, entry_b_id, "
    "team_a_score, team_b_score, winner_entry_id, status, format_code, format_version, "
    "format_snapshot, called_at, started_at, finished_at, created_at"
)
_RUBBER_COLS = (
    "id, team_tie_id, sequence, rubber_type, home_slots_json, away_slots_json, status, "
    "match_id, created_at, home_player_ids_json, away_player_ids_json, home_score, away_score, "
    "winner_entry_id, started_at, finished_at"
)


def create_team_tie(
    conn: sqlite3.Connection,
    tournament_id: int,
    stage: str,
    group_id: int | None,
    round_num: int,
    match_index: int | None,
    entry_a_id: int,
    entry_b_id: int,
) -> dict:
    cur = conn.execute(
        "INSERT INTO team_ties (tournament_id, stage, group_id, round, match_index, entry_a_id, entry_b_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tournament_id, stage, group_id, round_num, match_index, entry_a_id, entry_b_id),
    )
    return get_team_tie(conn, int(cur.lastrowid))


def get_team_tie(conn: sqlite3.Connection, tie_id: int) -> Optional[dict]:
    row = conn.execute(f"SELECT {_TIE_COLS} FROM team_ties WHERE id = ?", (tie_id,)).fetchone()
    return dict(row) if row else None


def list_team_ties(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_TIE_COLS} FROM team_ties WHERE tournament_id = ? ORDER BY id",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_team_ties(
    conn: sqlite3.Connection, tournament_id: int, stage: str | None = None
) -> int:
    """某赛事（可选：某赛段）的对抗数量。

    只回答"有没有"，不解释业务含义：重复生成的判定写在 services/team_ties.py，
    repository 不参与任何编排或业务规则。
    """
    if stage is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM team_ties WHERE tournament_id = ?", (tournament_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM team_ties WHERE tournament_id = ? AND stage = ?",
            (tournament_id, stage),
        ).fetchone()
    return int(row["n"])


def list_group_team_ties(
    conn: sqlite3.Connection, tournament_id: int, group_id: int
) -> list[dict]:
    """某小组的对抗（按 round, match_index, id 稳定排序），供生成器按组校验与统计。"""
    rows = conn.execute(
        f"SELECT {_TIE_COLS} FROM team_ties "
        "WHERE tournament_id = ? AND group_id = ? "
        "ORDER BY round, COALESCE(match_index, 0), id",
        (tournament_id, group_id),
    ).fetchall()
    return [dict(r) for r in rows]


def list_group_team_ties_with_rubbers(
    conn: sqlite3.Connection, tournament_id: int, group_id: int
) -> list[dict]:
    """某小组的对抗**连同各盘的排名相关字段**（团体小组排名用，一次 JOIN 查询）。

    只取排名需要的列：盘序、状态、胜者与局分。`home_score` / `away_score` 就是该对抗
    A 队 / B 队视角的局分（不新增任何逐局小表）。排序稳定：对抗按 round/match_index/id，
    盘按 sequence。这里只做 SQL，不解释业务含义。
    """
    ties = conn.execute(
        f"SELECT {_TIE_COLS} FROM team_ties "
        "WHERE tournament_id = ? AND group_id = ? AND stage = 'GROUP' "
        "ORDER BY round, COALESCE(match_index, 0), id",
        (tournament_id, group_id),
    ).fetchall()
    rubbers = conn.execute(
        "SELECT r.team_tie_id, r.id, r.sequence, r.status, r.winner_entry_id, "
        "r.home_score, r.away_score "
        "FROM team_rubbers r JOIN team_ties t ON t.id = r.team_tie_id "
        "WHERE t.tournament_id = ? AND t.group_id = ? AND t.stage = 'GROUP' "
        "ORDER BY r.team_tie_id, r.sequence",
        (tournament_id, group_id),
    ).fetchall()
    by_tie: dict[int, list[dict]] = {}
    for row in rubbers:
        item = dict(row)
        by_tie.setdefault(item["team_tie_id"], []).append(item)

    result = []
    for row in ties:
        tie = dict(row)
        tie["rubbers"] = by_tie.get(tie["id"], [])
        result.append(tie)
    return result


def set_team_tie_format(
    conn: sqlite3.Connection,
    tie_id: int,
    format_code: str,
    format_version: int,
    format_snapshot: str,
) -> dict:
    """固化该场对抗使用的赛制（code + version + 快照 JSON）。"""
    conn.execute(
        "UPDATE team_ties SET format_code = ?, format_version = ?, format_snapshot = ? WHERE id = ?",
        (format_code, format_version, format_snapshot, tie_id),
    )
    return get_team_tie(conn, tie_id)


# ------------------------------------------------ 团体赛晋级确认（A6.3）
#
# 只记录"哪些队伍已被确认晋级"。排名事实不在这里存：需要排名时永远从
# team_ties / team_rubbers 现算（A6.2），避免第二真相源。

_TEAM_QUALIFICATION_COLS = (
    "id, tournament_id, team_entry_id, group_id, status, confirmed_at"
)


def create_team_qualification(
    conn: sqlite3.Connection,
    tournament_id: int,
    team_entry_id: int,
    group_id: int | None,
) -> dict:
    """写入一条晋级确认（不 commit，事务边界由调用方决定）。"""
    cur = conn.execute(
        "INSERT INTO team_qualifications (tournament_id, team_entry_id, group_id) "
        "VALUES (?, ?, ?)",
        (tournament_id, team_entry_id, group_id),
    )
    return get_team_qualification(conn, int(cur.lastrowid))


def get_team_qualification(
    conn: sqlite3.Connection, qualification_id: int
) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_TEAM_QUALIFICATION_COLS} FROM team_qualifications WHERE id = ?",
        (qualification_id,),
    ).fetchone()
    return dict(row) if row else None


def list_team_qualifications(
    conn: sqlite3.Connection, tournament_id: int
) -> list[dict]:
    """某赛事全部晋级确认（按队伍 id 稳定排序；顺序不代表名次）。"""
    rows = conn.execute(
        f"SELECT {_TEAM_QUALIFICATION_COLS} FROM team_qualifications "
        "WHERE tournament_id = ? ORDER BY team_entry_id",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_team_qualifications(conn: sqlite3.Connection, tournament_id: int) -> int:
    """清空某赛事的晋级确认（重新确认前调用），返回删除行数。"""
    cur = conn.execute(
        "DELETE FROM team_qualifications WHERE tournament_id = ?", (tournament_id,)
    )
    return cur.rowcount


def create_team_rubber(
    conn: sqlite3.Connection,
    team_tie_id: int,
    sequence: int,
    rubber_type: str,
    home_slots_json: str,
    away_slots_json: str,
) -> dict:
    """写入一盘骨架；match_id 保持 NULL（A3 不创建 Match）。"""
    cur = conn.execute(
        "INSERT INTO team_rubbers (team_tie_id, sequence, rubber_type, home_slots_json, away_slots_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (team_tie_id, sequence, rubber_type, home_slots_json, away_slots_json),
    )
    return get_team_rubber(conn, int(cur.lastrowid))


def get_team_rubber(conn: sqlite3.Connection, rubber_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_RUBBER_COLS} FROM team_rubbers WHERE id = ?", (rubber_id,)
    ).fetchone()
    return dict(row) if row else None


def list_team_rubbers(conn: sqlite3.Connection, tie_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_RUBBER_COLS} FROM team_rubbers WHERE team_tie_id = ? ORDER BY sequence",
        (tie_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_tournament_team_rubbers(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """某赛事全部盘骨架与运行态（导出用，一次 JOIN 查询）。"""
    rows = conn.execute(
        f"SELECT r.id, r.team_tie_id, r.sequence, r.rubber_type, r.home_slots_json, "
        f"r.away_slots_json, r.status, r.match_id, r.created_at, r.home_player_ids_json, "
        f"r.away_player_ids_json, r.home_score, r.away_score, r.winner_entry_id, "
        f"r.started_at, r.finished_at "
        f"FROM team_rubbers r JOIN team_ties t ON t.id = r.team_tie_id "
        f"WHERE t.tournament_id = ? ORDER BY r.team_tie_id, r.sequence",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------- 团体赛运行态（A4.1：lineup 绑定 / 盘比分 / 生命周期）
#
# 这些写入一律是"带预期旧状态的条件更新"，并返回是否真的命中了目标状态（rowcount == 1）：
# 调用方必须先 SELECT 做业务校验，但**判断结论必须由条件更新兜底**，
# 否则两个并发请求（各自独立 SQLite 连接）可以同时通过校验、再依次无条件写入，
# 从而绕过"最多一盘 PLAYING""PLAYING 不能被写回 READY""FINISHED 不能改分"等状态机约束。

def set_team_rubber_lineup(
    conn: sqlite3.Connection,
    rubber_id: int,
    home_player_ids_json: str,
    away_player_ids_json: str,
) -> bool:
    """写入本盘实际参赛人，并把 PENDING → READY。

    只允许 PENDING/READY → READY：盘一旦进入 PLAYING/FINISHED/SKIPPED，这次更新不会命中，
    因此并发下"先通过校验的 lineup 更新"不可能把 PLAYING 反向写回 READY。
    """
    cur = conn.execute(
        "UPDATE team_rubbers SET home_player_ids_json = ?, away_player_ids_json = ?, "
        "status = 'READY' WHERE id = ? AND status IN ('PENDING','READY')",
        (home_player_ids_json, away_player_ids_json, rubber_id),
    )
    return cur.rowcount == 1


def mark_team_rubber_playing(conn: sqlite3.Connection, rubber_id: int) -> bool:
    """READY → PLAYING（原子）：只有当前仍是 READY 的盘才会被写成 PLAYING。"""
    cur = conn.execute(
        "UPDATE team_rubbers SET status = 'PLAYING', started_at = ? WHERE id = ? AND status = 'READY'",
        (utc_now(conn), rubber_id),
    )
    return cur.rowcount == 1


def mark_team_rubber_finished(
    conn: sqlite3.Connection,
    rubber_id: int,
    home_score: int,
    away_score: int,
    winner_entry_id: int,
) -> bool:
    """PLAYING → FINISHED（原子）：只有当前仍是 PLAYING 的盘才会被结算。

    并发重复录分时，第二个请求命中 0 行，调用方据此返回 409——本版"不支持改分"
    因此在数据库层成立，而不是只靠接口层的读后判断。
    """
    cur = conn.execute(
        "UPDATE team_rubbers SET status = 'FINISHED', home_score = ?, away_score = ?, "
        "winner_entry_id = ?, finished_at = ? WHERE id = ? AND status = 'PLAYING'",
        (home_score, away_score, winner_entry_id, utc_now(conn), rubber_id),
    )
    return cur.rowcount == 1


def list_playing_team_rubbers(conn: sqlite3.Connection, tie_id: int) -> list[dict]:
    """该对抗当前进行中的盘（含盘 id/序号），用于"同时最多一盘 PLAYING"的校验。"""
    rows = conn.execute(
        f"SELECT {_RUBBER_COLS} FROM team_rubbers "
        f"WHERE team_tie_id = ? AND status = 'PLAYING' ORDER BY sequence",
        (tie_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def skip_open_team_rubbers(conn: sqlite3.Connection, tie_id: int) -> int:
    """对抗提前结束后，把还没打的盘（PENDING/READY）标成 SKIPPED；FINISHED/PLAYING 不动。"""
    cur = conn.execute(
        "UPDATE team_rubbers SET status = 'SKIPPED' "
        "WHERE team_tie_id = ? AND status IN ('PENDING','READY')",
        (tie_id,),
    )
    return cur.rowcount


def set_team_tie_scores(
    conn: sqlite3.Connection, tie_id: int, team_a_score: int, team_b_score: int
) -> None:
    """对抗总分永远由后端按 FINISHED 的盘重算后写入（不接受客户端传入）。"""
    conn.execute(
        "UPDATE team_ties SET team_a_score = ?, team_b_score = ? WHERE id = ?",
        (team_a_score, team_b_score, tie_id),
    )


def mark_team_tie_playing(conn: sqlite3.Connection, tie_id: int) -> bool:
    """对抗首次有盘开始：WAITING → PLAYING（called_at 与 started_at 同源记录，只写一次）。"""
    now = utc_now(conn)
    cur = conn.execute(
        "UPDATE team_ties SET status = 'PLAYING', called_at = COALESCE(called_at, ?), "
        "started_at = COALESCE(started_at, ?) WHERE id = ? AND status = 'WAITING'",
        (now, now, tie_id),
    )
    return cur.rowcount == 1


def mark_team_tie_finished(conn: sqlite3.Connection, tie_id: int, winner_entry_id: int) -> bool:
    """对抗达到获胜盘数：FINISHED + 胜者 + 结束时间（只从非 FINISHED 状态迁移一次）。"""
    cur = conn.execute(
        "UPDATE team_ties SET status = 'FINISHED', winner_entry_id = ?, finished_at = ? "
        "WHERE id = ? AND status != 'FINISHED'",
        (winner_entry_id, utc_now(conn), tie_id),
    )
    return cur.rowcount == 1


def delete_team_rubbers_for_tie(conn: sqlite3.Connection, tie_id: int) -> None:
    conn.execute("DELETE FROM team_rubbers WHERE team_tie_id = ?", (tie_id,))


def find_tie_referencing_entry(conn: sqlite3.Connection, entry_id: int) -> Optional[dict]:
    """查某队伍是否已被团体对抗引用（有引用时禁止删除该 Entry）。"""
    row = conn.execute(
        "SELECT id, tournament_id FROM team_ties WHERE entry_a_id = ? OR entry_b_id = ? "
        "ORDER BY id LIMIT 1",
        (entry_id, entry_id),
    ).fetchone()
    return dict(row) if row else None


def find_started_tie_for_entry(conn: sqlite3.Connection, entry_id: int) -> Optional[dict]:
    """查该队伍是否已有"已经开始或已结束"的对抗（PLAYING/FINISHED）。

    这是名单冻结的依据：一旦队伍进入 Runtime（有盘开始），队员名单就不允许再改，
    否则已提交的 lineup 可能在开赛后指向"已经不属于该队"的选手。
    """
    row = conn.execute(
        "SELECT id, status FROM team_ties WHERE (entry_a_id = ? OR entry_b_id = ?) "
        "AND status IN ('PLAYING','FINISHED') ORDER BY id LIMIT 1",
        (entry_id, entry_id),
    ).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------ groups

_GROUP_COLS = "id, tournament_id, name, sort_order, qualify_count"


def create_group(
    conn: sqlite3.Connection, tournament_id: int, name: str, sort_order: int
) -> dict:
    cur = conn.execute(
        "INSERT INTO groups (tournament_id, name, sort_order) VALUES (?, ?, ?)",
        (tournament_id, name, sort_order),
    )
    row = conn.execute(
        f"SELECT {_GROUP_COLS} FROM groups WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def list_groups(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_GROUP_COLS} FROM groups WHERE tournament_id = ? ORDER BY sort_order",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_group(conn: sqlite3.Connection, group_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_GROUP_COLS} FROM groups WHERE id = ?", (group_id,)
    ).fetchone()
    return dict(row) if row else None


def update_group_qualify_count(
    conn: sqlite3.Connection, group_id: int, qualify_count: int
) -> dict | None:
    conn.execute(
        "UPDATE groups SET qualify_count = ? WHERE id = ?", (qualify_count, group_id)
    )
    conn.commit()
    return get_group(conn, group_id)


# ------------------------------------------------ qualification decisions

def create_qualification_decision(
    conn: sqlite3.Connection,
    tournament_id: int,
    group_id: int,
    selected_entry_ids: str,
    ranking_snapshot: str,
    reason: str,
    operator_name: str,
) -> dict:
    cur = conn.execute(
        "INSERT INTO qualification_decisions "
        "(tournament_id, group_id, selected_entry_ids, ranking_snapshot, reason, operator_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tournament_id, group_id, selected_entry_ids, ranking_snapshot, reason, operator_name),
    )
    return get_qualification_decision(conn, cur.lastrowid)


def get_qualification_decision(
    conn: sqlite3.Connection, decision_id: int
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM qualification_decisions WHERE id = ?", (decision_id,)
    ).fetchone()
    return dict(row) if row else None


def get_active_qualification_decision(
    conn: sqlite3.Connection, group_id: int
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM qualification_decisions "
        "WHERE group_id = ? AND invalidated_at IS NULL ORDER BY id DESC LIMIT 1",
        (group_id,),
    ).fetchone()
    return dict(row) if row else None


def list_qualification_decisions(
    conn: sqlite3.Connection, group_id: int
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM qualification_decisions WHERE group_id = ? ORDER BY id DESC",
        (group_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def invalidate_qualification_decision(
    conn: sqlite3.Connection, group_id: int, reason: str
) -> bool:
    cur = conn.execute(
        "UPDATE qualification_decisions "
        "SET invalidated_at = datetime('now'), invalidation_reason = ? "
        "WHERE group_id = ? AND invalidated_at IS NULL",
        (reason, group_id),
    )
    return cur.rowcount > 0


def delete_groups_for_tournament(conn: sqlite3.Connection, tournament_id: int) -> None:
    conn.execute("DELETE FROM groups WHERE tournament_id = ?", (tournament_id,))


# ------------------------------------------------------------------ 分组归属

def clear_player_groups(conn: sqlite3.Connection, tournament_id: int) -> None:
    """清空某赛事所有选手的分组归属。"""
    conn.execute(
        "UPDATE players SET group_id = NULL WHERE tournament_id = ?", (tournament_id,)
    )


def set_player_group(conn: sqlite3.Connection, player_id: int, group_id: int) -> None:
    conn.execute("UPDATE players SET group_id = ? WHERE id = ?", (group_id, player_id))


# ------------------------------------------------------------------ matches

def create_match(
    conn: sqlite3.Connection,
    tournament_id: int,
    stage: str,
    group_id: int | None,
    round_num: int,
    match_index: int | None,
    player_a_id: int | None,
    player_b_id: int | None,
    prev_match_a_id: int | None = None,
    prev_match_b_id: int | None = None,
    prev_match_a_outcome: str = "WINNER",
    prev_match_b_outcome: str = "WINNER",
    entry_a_id: int | None = None,
    entry_b_id: int | None = None,
    bracket: str | None = None,
    placement_min: int | None = None,
    placement_max: int | None = None,
) -> dict:
    cur = conn.execute(
        "INSERT INTO matches (tournament_id, stage, group_id, round, match_index, "
        "player_a_id, player_b_id, prev_match_a_id, prev_match_b_id, prev_match_a_outcome, prev_match_b_outcome, entry_a_id, entry_b_id, "
        "bracket, placement_min, placement_max) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tournament_id,
            stage,
            group_id,
            round_num,
            match_index,
            player_a_id,
            player_b_id,
            prev_match_a_id,
            prev_match_b_id,
            prev_match_a_outcome,
            prev_match_b_outcome,
            entry_a_id,
            entry_b_id,
            bracket or ("GROUP" if stage == "GROUP" else "MAIN"),
            placement_min,
            placement_max,
        ),
    )
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_matches(
    conn: sqlite3.Connection,
    tournament_id: int,
    stage: str | None = None,
    status: str | None = None,
    group_id: int | None = None,
) -> list[dict]:
    sql = "SELECT * FROM matches WHERE tournament_id = ?"
    params: list[Any] = [tournament_id]
    if stage is not None:
        sql += " AND stage = ?"
        params.append(stage)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if group_id is not None:
        sql += " AND group_id = ?"
        params.append(group_id)
    sql += " ORDER BY id"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_matches(
    conn: sqlite3.Connection, tournament_id: int, stage: str | None = None
) -> int:
    sql = "SELECT COUNT(*) FROM matches WHERE tournament_id = ?"
    params: list[Any] = [tournament_id]
    if stage is not None:
        sql += " AND stage = ?"
        params.append(stage)
    return conn.execute(sql, params).fetchone()[0]


def get_match(conn: sqlite3.Connection, match_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------- 比赛时间（A2 时间基础）

# 统一时间约定：UTC SQLite 时间戳，格式 'YYYY-MM-DD HH:MM:SS'（与 created_at 等既有字段一致）。
# 所有比赛生命周期时间只能通过下面三个 helper 写入，避免时间语义散落在各 service 里。
# 语义：
#   called_at   最近一次正式把该比赛安排到球台的时间（release 后保留，重新安排时刷新）
#   started_at  当前有效"进行中"比赛的实际开始时间（release 后置空，重新安排时重写）
#   finished_at 当前有效比赛产生最终结果的时间（revise_score 纠错时不改变）


def utc_now(conn: sqlite3.Connection) -> str:
    """当前 UTC 时间（SQLite 时钟，与其它 datetime('now') 字段同源）。"""
    return conn.execute("SELECT datetime('now')").fetchone()[0]


def mark_match_playing(conn: sqlite3.Connection, match_id: int, table_id: int) -> None:
    """WAITING → PLAYING：写入/刷新 called_at 与 started_at（同一时刻）。"""
    now = utc_now(conn)
    conn.execute(
        "UPDATE matches SET status = 'PLAYING', table_id = ?, called_at = ?, started_at = ? "
        "WHERE id = ?",
        (table_id, now, now, match_id),
    )


def mark_match_waiting(conn: sqlite3.Connection, match_id: int) -> None:
    """PLAYING → WAITING（下球台）：本次上台不构成有效进行中比赛，started_at 置空。

    called_at 保留"最近一次叫号"的事实，重新安排时会被刷新。
    """
    conn.execute(
        "UPDATE matches SET status = 'WAITING', table_id = NULL, started_at = NULL WHERE id = ?",
        (match_id,),
    )


def mark_match_finished(conn: sqlite3.Connection, match_id: int, **fields: Any) -> dict:
    """把比赛置为 FINISHED 并写入 finished_at（UTC）。

    既覆盖 PLAYING → FINISHED，也覆盖 WAITING 直接录分（此时 started_at 保持为空，
    不伪造开始时间，避免产生 0 秒样本）；系统轮空不经过本函数。
    """
    unknown = set(fields) - _MATCH_UPDATEABLE
    if unknown:
        raise ValueError(f"不允许更新的字段: {sorted(unknown)}")
    fields["status"] = "FINISHED"
    fields["finished_at"] = utc_now(conn)
    sets = [f"{key} = ?" for key in fields]
    params: list[Any] = list(fields.values()) + [match_id]
    conn.execute(f"UPDATE matches SET {', '.join(sets)} WHERE id = ?", params)
    return get_match(conn, match_id)


_MATCH_UPDATEABLE = {
    "status",
    "table_id",
    "player_a_id",
    "player_b_id",
    "player_a_score",
    "player_b_score",
    "winner_id",
    "entry_a_id",
    "entry_b_id",
    "winner_entry_id",
    "result_type",
    "forfeit_entry_id",
    "result_note",
    "bracket",
    "placement_min",
    "placement_max",
    "started_at",
    "finished_at",
}


def update_match(conn: sqlite3.Connection, match_id: int, **fields) -> dict:
    """按给定字段更新比赛；只允许更新白名单字段。返回更新后的比赛。"""
    unknown = set(fields) - _MATCH_UPDATEABLE
    if unknown:
        raise ValueError(f"不允许更新的字段: {sorted(unknown)}")
    if fields:
        sets = [f"{k} = ?" for k in fields]
        params: list[Any] = list(fields.values()) + [match_id]
        conn.execute(
            f"UPDATE matches SET {', '.join(sets)} WHERE id = ?", params
        )
    return get_match(conn, match_id)


def create_score_audit(
    conn: sqlite3.Connection,
    match_id: int,
    action: str,
    before_snapshot: str,
    after_snapshot: str,
    operator_name: str | None,
    change_reason: str | None,
    request_id: str | None,
) -> dict:
    cur = conn.execute(
        "INSERT INTO score_audits "
        "(match_id, action, before_snapshot, after_snapshot, operator_name, change_reason, request_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (match_id, action, before_snapshot, after_snapshot, operator_name, change_reason, request_id),
    )
    row = conn.execute("SELECT * FROM score_audits WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_score_audits(conn: sqlite3.Connection, match_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM score_audits WHERE match_id = ? ORDER BY id DESC", (match_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def claim_score_request(
    conn: sqlite3.Connection,
    request_id: str,
    match_id: int,
    action: str,
    payload_fingerprint: str,
) -> str:
    """认领比分请求；返回 NEW、REPLAY 或 CONFLICT。"""
    try:
        conn.execute(
            "INSERT INTO score_requests (request_id, match_id, action, payload_fingerprint) VALUES (?, ?, ?, ?)",
            (request_id, match_id, action, payload_fingerprint),
        )
        return "NEW"
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT match_id, action, payload_fingerprint FROM score_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row and (row["match_id"], row["action"], row["payload_fingerprint"]) == (
            match_id, action, payload_fingerprint
        ):
            return "REPLAY"
        return "CONFLICT"


def list_playing_matches(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM matches WHERE tournament_id = ? AND status = 'PLAYING'",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_matches_by_prev(conn: sqlite3.Connection, match_id: int) -> list[dict]:
    """引用本场比赛胜者或负者作为来源的后续比赛。"""
    rows = conn.execute(
        "SELECT * FROM matches WHERE prev_match_a_id = ? OR prev_match_b_id = ?",
        (match_id, match_id),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_match(conn: sqlite3.Connection, match_id: int) -> bool:
    """删除一场比赛（match_games / score_requests 由外键级联清理）。

    调用方必须保证没有其它比赛通过 prev_match_a_id / prev_match_b_id 引用它。
    """
    cur = conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    return cur.rowcount > 0


def replace_match_games(
    conn: sqlite3.Connection,
    match_id: int,
    games: list[tuple[int, int]],
    entry_a_id: int | None,
    entry_b_id: int | None,
) -> list[dict]:
    conn.execute("DELETE FROM match_games WHERE match_id = ?", (match_id,))
    for game_no, (score_a, score_b) in enumerate(games, start=1):
        winner = entry_a_id if score_a > score_b else entry_b_id
        conn.execute(
            "INSERT INTO match_games (match_id, game_no, side_a_score, side_b_score, winner_entry_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (match_id, game_no, score_a, score_b, winner),
        )
    return list_match_games(conn, match_id)


def list_match_games(conn: sqlite3.Connection, match_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, match_id, game_no, side_a_score, side_b_score, winner_entry_id "
        "FROM match_games WHERE match_id = ? ORDER BY game_no",
        (match_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_tournament_match_games(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """某赛事全部逐局比分（导出用，一次查询避免逐场查询）。"""
    rows = conn.execute(
        "SELECT g.id, g.match_id, g.game_no, g.side_a_score, g.side_b_score, g.winner_entry_id "
        "FROM match_games g JOIN matches m ON m.id = g.match_id "
        "WHERE m.tournament_id = ? ORDER BY g.match_id, g.game_no",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_tournament_score_requests(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """某赛事的比分写入审计账本（幂等编号 / 动作 / 指纹 / 时间）。"""
    rows = conn.execute(
        "SELECT s.request_id, s.match_id, s.action, s.payload_fingerprint, s.created_at "
        "FROM score_requests s JOIN matches m ON m.id = s.match_id "
        "WHERE m.tournament_id = ? ORDER BY s.created_at, s.request_id",
        (tournament_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def decorate_match(conn: sqlite3.Connection, match: dict) -> dict:
    result = dict(match)
    entries = {}
    for key in ("entry_a_id", "entry_b_id"):
        entry_id = result.get(key)
        if entry_id is not None:
            entries[entry_id] = get_entry(conn, entry_id)
    result["entry_a_name"] = (entries.get(result.get("entry_a_id")) or {}).get("display_name")
    result["entry_b_name"] = (entries.get(result.get("entry_b_id")) or {}).get("display_name")
    result["games"] = list_match_games(conn, result["id"])
    return result


# ------------------------------------------------------------------- auth

_USER_COLS = (
    "id, username, display_name, phone, note, password_hash, system_role, active, "
    "created_at, updated_at"
)


def create_user(
    conn: sqlite3.Connection,
    username: str,
    display_name: str,
    password_hash: str,
    system_role: str,
    phone: str | None = None,
    note: str | None = None,
) -> dict:
    cur = conn.execute(
        "INSERT INTO users "
        "(username, display_name, password_hash, system_role, phone, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, display_name, password_hash, system_role, phone, note),
    )
    row = conn.execute(
        f"SELECT {_USER_COLS} FROM users WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def get_user_by_username(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_USER_COLS} FROM users WHERE username = ? COLLATE NOCASE",
        (username,),
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_USER_COLS} FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def get_bootstrap_completed(conn: sqlite3.Connection) -> Optional[bool]:
    row = conn.execute(
        "SELECT bootstrap_completed FROM system_state WHERE id = 1"
    ).fetchone()
    return bool(row["bootstrap_completed"]) if row else None


def has_active_system_admin(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM users "
        "WHERE system_role = 'SYSTEM_ADMIN' AND active = 1"
    ).fetchone()
    return int(row["count"]) > 0


def mark_bootstrap_completed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE system_state SET bootstrap_completed = 1, "
        "updated_at = datetime('now') WHERE id = 1"
    )


def update_user_password(
    conn: sqlite3.Connection, user_id: int, password_hash: str
) -> None:
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
        (password_hash, user_id),
    )


def set_user_active(conn: sqlite3.Connection, user_id: int, active: bool) -> None:
    conn.execute(
        "UPDATE users SET active = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if active else 0, user_id),
    )


def create_user_session(
    conn: sqlite3.Connection,
    user_id: int,
    token_hash: str,
    expires_at: str,
) -> dict:
    cur = conn.execute(
        "INSERT INTO user_sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
        (user_id, token_hash, expires_at),
    )
    row = conn.execute(
        "SELECT id, user_id, token_hash, expires_at, revoked_at, last_seen_at, created_at "
        "FROM user_sessions WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return dict(row)


def get_user_session_by_token_hash(
    conn: sqlite3.Connection, token_hash: str
) -> Optional[dict]:
    row = conn.execute(
        "SELECT s.id AS session_id, s.user_id, s.token_hash, s.expires_at, s.revoked_at, "
        "s.last_seen_at, s.created_at, u.username, u.display_name, u.password_hash, "
        "u.system_role, u.active, u.created_at AS user_created_at, "
        "u.updated_at AS user_updated_at "
        "FROM user_sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ?",
        (token_hash,),
    ).fetchone()
    return dict(row) if row else None


def touch_user_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE user_sessions SET last_seen_at = datetime('now') WHERE id = ?",
        (session_id,),
    )


def revoke_user_session_by_hash(conn: sqlite3.Connection, token_hash: str) -> bool:
    cur = conn.execute(
        "UPDATE user_sessions SET revoked_at = datetime('now') "
        "WHERE token_hash = ? AND revoked_at IS NULL",
        (token_hash,),
    )
    return cur.rowcount > 0


def revoke_user_sessions(conn: sqlite3.Connection, user_id: int) -> int:
    cur = conn.execute(
        "UPDATE user_sessions SET revoked_at = datetime('now') "
        "WHERE user_id = ? AND revoked_at IS NULL",
        (user_id,),
    )
    return cur.rowcount


def upsert_tournament_admin(
    conn: sqlite3.Connection,
    tournament_id: int,
    user_id: int,
    role: str,
    created_by_user_id: int | None = None,
) -> dict:
    """新增或恢复赛事授权；同一赛事-用户组合只保留一条有效授权。"""
    conn.execute(
        "INSERT INTO tournament_admins "
        "(tournament_id, user_id, role, created_by_user_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, tournament_id) DO UPDATE SET "
        "role = excluded.role, created_by_user_id = excluded.created_by_user_id, "
        "revoked_at = NULL",
        (tournament_id, user_id, role, created_by_user_id),
    )
    row = conn.execute(
        "SELECT id, tournament_id, user_id, role, created_by_user_id, revoked_at, created_at "
        "FROM tournament_admins WHERE tournament_id = ? AND user_id = ?",
        (tournament_id, user_id),
    ).fetchone()
    return dict(row)


def get_tournament_access(
    conn: sqlite3.Connection, tournament_id: int, user_id: int
) -> Optional[dict]:
    """返回用户在指定赛事中的角色；不存在或无权访问时返回 None。"""
    row = conn.execute(
        "SELECT t.id AS tournament_id, "
        "CASE WHEN t.owner_user_id = ? THEN 'OWNER' ELSE ta.role END AS role "
        "FROM tournaments t "
        "LEFT JOIN tournament_admins ta ON ta.tournament_id = t.id "
        "AND ta.user_id = ? AND ta.revoked_at IS NULL "
        "WHERE t.id = ? AND (t.owner_user_id = ? OR ta.role IS NOT NULL)",
        (user_id, user_id, tournament_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def count_tournament_access(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM tournaments t "
        "WHERE t.owner_user_id = ? OR EXISTS ("
        "SELECT 1 FROM tournament_admins ta WHERE ta.tournament_id = t.id "
        "AND ta.user_id = ? AND ta.revoked_at IS NULL)",
        (user_id, user_id),
    ).fetchone()
    return int(row["count"])


def list_tournaments_for_user(
    conn: sqlite3.Connection, user_id: int
) -> list[dict]:
    """只返回当前用户为 Owner 或拥有有效赛事授权的赛事。"""
    rows = conn.execute(
        f"SELECT {_TOURNAMENT_COLS} FROM tournaments t "
        "WHERE t.owner_user_id = ? OR EXISTS ("
        "SELECT 1 FROM tournament_admins ta WHERE ta.tournament_id = t.id "
        "AND ta.user_id = ? AND ta.revoked_at IS NULL) "
        "ORDER BY t.id DESC",
        (user_id, user_id),
    ).fetchall()
    return [dict(r) for r in rows]
