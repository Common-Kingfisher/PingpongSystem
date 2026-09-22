"""赛事服务：创建赛事（含自动生成球台）等事务性编排。"""

import sqlite3

from .. import repository as repo
from ..models import TournamentRole


def create_tournament_with_tables(
    conn: sqlite3.Connection,
    name: str,
    date,
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
    """在同一个事务中创建赛事、赛事 Owner 授权和球台。"""
    try:
        tournament = repo.create_tournament(
            conn,
            name,
            date.isoformat(),
            table_count,
            group_count,
            qualify_per_group,
            event_type,
            bronze_mode,
            placement_mode,
            games_to_win,
            points_to_win,
            operation_mode,
            owner_user_id=owner_user_id,
        )
        if owner_user_id is not None:
            repo.upsert_tournament_admin(
                conn,
                tournament["id"],
                owner_user_id,
                TournamentRole.OWNER.value,
                created_by_user_id=owner_user_id,
            )
        repo.create_tables_for_tournament(conn, tournament["id"], table_count)
        conn.commit()
        return tournament
    except Exception:
        conn.rollback()
        raise
