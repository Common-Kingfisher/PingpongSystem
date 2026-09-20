"""秩序册一致性快照：在同一 SQLite 读事务中聚合全部打印数据。"""

import sqlite3

from .. import repository as repo
from . import groups as groups_service
from . import knockout as knockout_service
from . import rankings as rankings_service
from . import scheduling as scheduling_service


class OrderBookError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def get_snapshot(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """返回同一数据库版本中的赛事、排名、签表、比赛和球台数据。"""
    conn.execute("BEGIN")
    try:
        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise OrderBookError("赛事不存在", 404)
        snapshot_at = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        ).fetchone()[0]
        matches = [
            repo.decorate_match(conn, match)
            for match in repo.list_matches(conn, tournament_id)
        ]
        snapshot = {
            "snapshot_at": snapshot_at,
            "tournament": tournament,
            "entries": repo.list_entries(conn, tournament_id),
            "groups": {"groups": groups_service.get_groups_with_players(conn, tournament_id)},
            "rankings": {"rankings": rankings_service.get_rankings(conn, tournament_id)},
            "tree": knockout_service.get_knockout(conn, tournament_id),
            "matches": matches,
            "dashboard": scheduling_service.get_dashboard(conn, tournament_id),
        }
        conn.commit()
        return snapshot
    except Exception:
        conn.rollback()
        raise
