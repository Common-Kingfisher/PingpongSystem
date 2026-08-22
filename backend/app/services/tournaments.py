"""赛事服务：创建赛事（含自动生成球台）等事务性编排。"""

import sqlite3

from .. import repository as repo


def create_tournament_with_tables(
    conn: sqlite3.Connection,
    name: str,
    date,
    table_count: int,
    group_count: int,
    qualify_per_group: int,
) -> dict:
    """在同一个事务中创建赛事并生成球台。"""
    tournament = repo.create_tournament(
        conn, name, date.isoformat(), table_count, group_count, qualify_per_group
    )
    repo.create_tables_for_tournament(conn, tournament["id"], table_count)
    conn.commit()
    return tournament
