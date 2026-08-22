"""排名聚合服务：按小组读取全部比赛并实时重算排名。"""

import sqlite3

from .. import repository as repo
from ..domain import ranking
from ..models import MatchStage, MatchStatus


class RankingError(Exception):
    def __init__(self, message: str, code: int = 404):
        super().__init__(message)
        self.code = code


def get_rankings(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """返回每个小组的排名（含进度、晋级标记、并列歧义标记）。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise RankingError("赛事不存在")

    players = repo.list_players(conn, tournament_id)
    name_by_id = {p["id"]: p["name"] for p in players}
    group_of = {p["id"]: p["group_id"] for p in players}
    groups = repo.list_groups(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id, stage=MatchStage.GROUP.value)

    qualify = tournament["qualify_per_group"]
    result = []
    for group in groups:
        group_matches = [m for m in matches if m["group_id"] == group["id"]]
        member_ids = [p["id"] for p in players if group_of[p["id"]] == group["id"]]
        entries = ranking.compute_group_rankings(group_matches, member_ids)
        for e in entries:
            e["name"] = name_by_id[e["player_id"]]
        qualified, ambiguous = ranking.compute_qualification(entries, qualify)
        for e in entries:
            e["qualified"] = e["player_id"] in qualified
        result.append(
            {
                "group_id": group["id"],
                "group_name": group["name"],
                "total_matches": len(group_matches),
                "finished_matches": sum(
                    1 for m in group_matches if m["status"] == MatchStatus.FINISHED.value
                ),
                "ambiguous_qualification": ambiguous,
                "entries": entries,
            }
        )
    return result
