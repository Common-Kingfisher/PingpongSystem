"""赛事结构化导出：在同一只读事务里聚合"落库数据"与"运行期推导结果"。

用于赛事结果归档、交给组委会、以及删除赛事前的人工备份。
导出是纯读操作，不修改任何业务数据；结构里显式区分：

  - 落库数据：tournament / players / entries / entry_members / groups / tables /
    matches / match_games / qualification_decisions / score_requests /
    team_ties / team_rubbers
  - 运行期推导：derived.rankings / derived.champion / derived.runner_up / derived.placements

`schema_version` 用于以后识别历史导出格式；新增字段属于向后兼容扩展。
团体赛的 team_ties / team_rubbers 是 A3 追加的字段：单打/双打赛事导出时它们恒为空数组，
结构版本仍是 "1.0"，不构成破坏性变更。
"""

import json
import sqlite3

from .. import repository as repo
from . import knockout as knockout_service
from . import rankings as rankings_service

# 导出结构版本：字段只做向后兼容的追加时保持主版本，破坏性调整时递增。
EXPORT_SCHEMA_VERSION = "1.0"


class ExportError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _decision_rows(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """人工裁定导出形态：解析 JSON 字段并补上 active，同时保留冻结的排名快照。"""
    rows = []
    for row in repo.list_qualification_decisions(conn, tournament_id):
        snapshot = json.loads(row["ranking_snapshot"] or "{}")
        if not isinstance(snapshot, dict):
            # 兼容历史/异常格式：导出不因快照形态不同而失败。
            snapshot = {"raw_snapshot": snapshot}
        rows.append(
            {
                "id": row["id"],
                "group_id": row["group_id"],
                "selected_entry_ids": json.loads(row["selected_entry_ids"]),
                "ranking_snapshot": snapshot,
                "reason": row["reason"],
                "operator_name": row["operator_name"],
                "created_at": row["created_at"],
                "invalidated_at": row["invalidated_at"],
                "invalidation_reason": row["invalidation_reason"],
                "active": row["invalidated_at"] is None,
            }
        )
    return rows


def get_export(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """返回赛事完整导出结构（只读，同一数据库版本内一致）。"""
    conn.execute("BEGIN")
    try:
        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise ExportError("赛事不存在", 404)
        exported_at = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        ).fetchone()[0]
        entries = repo.list_entries(conn, tournament_id)
        tree = knockout_service.get_knockout(conn, tournament_id)
        result = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": exported_at,
            "tournament": tournament,
            "players": repo.list_players(conn, tournament_id),
            "entries": entries,
            # entry_members 与 entries[].members 内容一致，额外提供扁平形式便于外部直接建表。
            "entry_members": [
                {
                    "entry_id": entry["id"],
                    "player_id": member["player_id"],
                    "member_order": member["member_order"],
                }
                for entry in entries
                for member in entry["members"]
            ],
            "groups": repo.list_groups(conn, tournament_id),
            "tables": repo.list_tables(conn, tournament_id),
            "matches": [
                repo.decorate_match(conn, match)
                for match in repo.list_matches(conn, tournament_id)
            ],
            "match_games": repo.list_tournament_match_games(conn, tournament_id),
            "qualification_decisions": _decision_rows(conn, tournament_id),
            "score_requests": repo.list_tournament_score_requests(conn, tournament_id),
            # 团体赛（A3）：非团体赛事这两个数组恒为空；rubbers 的 match_id 在 A3 恒为 None。
            "team_ties": repo.list_team_ties(conn, tournament_id),
            "team_rubbers": repo.list_tournament_team_rubbers(conn, tournament_id),
            "derived": {
                "rankings": rankings_service.get_rankings(conn, tournament_id),
                "champion": tree["champion"],
                "runner_up": tree["runner_up"],
                "placements": tree["placements"],
            },
        }
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
