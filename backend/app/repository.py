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
    "roster_confirmed, confirmed_at"
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
) -> dict:
    cur = conn.execute(
        "INSERT INTO tournaments (name, date, table_count, group_count, qualify_per_group, "
        "event_type, bronze_mode, placement_mode, games_to_win, points_to_win) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, date, table_count, group_count, qualify_per_group, event_type,
         bronze_mode, placement_mode, games_to_win, points_to_win),
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


def delete_player(conn: sqlite3.Connection, player_id: int) -> bool:
    cur = conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    return cur.rowcount > 0


def clear_tournament_seeds(conn: sqlite3.Connection, tournament_id: int) -> None:
    """清空某赛事所有选手的种子序号。"""
    conn.execute("UPDATE players SET seed_no = NULL WHERE tournament_id = ?", (tournament_id,))


def set_player_seed(conn: sqlite3.Connection, player_id: int, seed_no: int) -> None:
    conn.execute("UPDATE players SET seed_no = ? WHERE id = ?", (seed_no, player_id))


# ------------------------------------------------------------------ entries

_ENTRY_COLS = "id, tournament_id, entry_type, display_name, rating_points, group_id, seed_no, status"


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
        "INSERT INTO entries (tournament_id, entry_type, display_name, rating_points, seed_no) "
        "VALUES (?, ?, ?, ?, ?)",
        (tournament_id, entry_type, display_name, rating_points, seed_no),
    )
    entry_id = int(cur.lastrowid)
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
        f"SELECT {_ENTRY_COLS} FROM entries WHERE tournament_id = ? ORDER BY id",
        (tournament_id,),
    ).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        entry["members"] = list_entry_members(conn, entry["id"])
        result.append(entry)
    return result


def clear_entry_groups(conn: sqlite3.Connection, tournament_id: int) -> None:
    conn.execute("UPDATE entries SET group_id = NULL WHERE tournament_id = ?", (tournament_id,))


def set_entry_group(conn: sqlite3.Connection, entry_id: int, group_id: int) -> None:
    conn.execute("UPDATE entries SET group_id = ? WHERE id = ?", (group_id, entry_id))


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
