"""SQL 访问层（repository）。

所有 SQL 集中在这里。函数接收 sqlite3.Connection，返回 dict 或 dict 列表。
业务规则（哪些操作被禁止等）不放在本层，放在 services/ 或 domain/。
"""

import sqlite3
from typing import Any, Optional

from .models import TableStatus

# ---------------------------------------------------------------- tournaments

_TOURNAMENT_COLS = "id, name, date, table_count, group_count, qualify_per_group, stage, created_at"


def create_tournament(
    conn: sqlite3.Connection,
    name: str,
    date: str,
    table_count: int,
    group_count: int,
    qualify_per_group: int,
) -> dict:
    cur = conn.execute(
        "INSERT INTO tournaments (name, date, table_count, group_count, qualify_per_group) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, date, table_count, group_count, qualify_per_group),
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

_PLAYER_COLS = "id, tournament_id, name, college, group_id"


def add_player(conn: sqlite3.Connection, tournament_id: int, name: str, college: Optional[str]) -> dict:
    cur = conn.execute(
        "INSERT INTO players (tournament_id, name, college) VALUES (?, ?, ?)",
        (tournament_id, name, college),
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
    conn: sqlite3.Connection, player_id: int, name: Optional[str], college: Optional[str]
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
    if sets:
        params.append(player_id)
        conn.execute(f"UPDATE players SET {', '.join(sets)} WHERE id = ?", params)
    return get_player(conn, player_id)


def delete_player(conn: sqlite3.Connection, player_id: int) -> bool:
    cur = conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
    return cur.rowcount > 0


# ------------------------------------------------------------------ groups

_GROUP_COLS = "id, tournament_id, name, sort_order"


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
) -> dict:
    cur = conn.execute(
        "INSERT INTO matches (tournament_id, stage, group_id, round, match_index, "
        "player_a_id, player_b_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tournament_id, stage, group_id, round_num, match_index, player_a_id, player_b_id),
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
    "player_a_score",
    "player_b_score",
    "winner_id",
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
