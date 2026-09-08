"""排名聚合服务：按小组读取全部比赛并实时重算排名。"""

import json
import sqlite3

from .. import repository as repo
from ..domain import ranking
from ..models import MatchStage, MatchStatus


class RankingError(Exception):
    def __init__(self, message: str, code: int = 404):
        super().__init__(message)
        self.code = code


def _cutoff_candidates(entries: list[dict], qualify: int) -> tuple[list[int], int]:
    """返回第一个跨越晋级线的并列组及该组剩余席位。"""
    groups: dict[int, list[int]] = {}
    for entry in sorted(entries, key=lambda item: (item["rank"], item["player_id"])):
        groups.setdefault(entry["rank"], []).append(entry["player_id"])
    accepted = 0
    for rank in sorted(groups):
        ids = groups[rank]
        remaining = qualify - accepted
        if remaining <= 0:
            break
        if len(ids) <= remaining:
            accepted += len(ids)
        else:
            return ids, remaining
    return [], 0


def qualification_snapshot(group: dict) -> str:
    """生成裁定依据快照；相关排名发生变化后旧裁定不得继续生效。"""
    data = {
        "group_id": group["group_id"],
        "qualify_count": group["qualify_count"],
        "finished_matches": group["finished_matches"],
        "total_matches": group["total_matches"],
        "entries": [
            {
                key: entry[key]
                for key in (
                    "player_id", "wins", "losses", "games_won", "games_lost",
                    "match_points", "points_won", "points_lost", "rank", "tied",
                )
            }
            for entry in sorted(group["entries"], key=lambda item: item["player_id"])
        ],
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decision_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "tournament_id": row["tournament_id"],
        "group_id": row["group_id"],
        "selected_entry_ids": json.loads(row["selected_entry_ids"]),
        "reason": row["reason"],
        "operator_name": row["operator_name"],
        "created_at": row["created_at"],
        "invalidated_at": row["invalidated_at"],
        "invalidation_reason": row["invalidation_reason"],
        "active": row["invalidated_at"] is None,
    }


def get_rankings(
    conn: sqlite3.Connection, tournament_id: int, include_decisions: bool = True
) -> list[dict]:
    """返回每个小组的排名（含进度、晋级标记、并列歧义标记）。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise RankingError("赛事不存在")

    players = repo.list_players(conn, tournament_id)
    entries = repo.list_entries(conn, tournament_id)
    use_entries = bool(entries)
    name_by_id = (
        {e["id"]: e["display_name"] for e in entries}
        if use_entries
        else {p["id"]: p["name"] for p in players}
    )
    group_of = (
        {e["id"]: e["group_id"] for e in entries}
        if use_entries
        else {p["id"]: p["group_id"] for p in players}
    )
    groups = repo.list_groups(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id, stage=MatchStage.GROUP.value)

    result = []
    for group in groups:
        qualify = group["qualify_count"] or tournament["qualify_per_group"]
        group_matches = [m for m in matches if m["group_id"] == group["id"]]
        source = entries if use_entries else players
        member_ids = [p["id"] for p in source if group_of[p["id"]] == group["id"]]
        ranked_entries = ranking.compute_group_rankings(
            [repo.decorate_match(conn, m) for m in group_matches], member_ids
        )
        for e in ranked_entries:
            e["name"] = name_by_id[e["player_id"]]
            e["entry_id"] = e["player_id"] if use_entries else None
        qualified, ambiguous = ranking.compute_qualification(ranked_entries, qualify)
        point_score_match_ids = ranking.missing_point_score_match_ids(
            [repo.decorate_match(conn, m) for m in group_matches], ranked_entries, qualify
        )
        for e in ranked_entries:
            e["qualified"] = e["player_id"] in qualified
        group_result = {
                "group_id": group["id"],
                "group_name": group["name"],
                "qualify_count": qualify,
                "total_matches": len(group_matches),
                "finished_matches": sum(
                    1 for m in group_matches if m["status"] == MatchStatus.FINISHED.value
                ),
                "ambiguous_qualification": ambiguous,
                "needs_point_scores": ambiguous and bool(point_score_match_ids),
                "point_score_match_ids": point_score_match_ids,
                "manually_resolved": False,
                "manual_candidate_entry_ids": [],
                "manual_slots_remaining": 0,
                "qualification_decision": None,
                "entries": ranked_entries,
            }
        if ambiguous:
            candidates, remaining = _cutoff_candidates(ranked_entries, qualify)
            group_result["manual_candidate_entry_ids"] = candidates
            group_result["manual_slots_remaining"] = remaining
        if include_decisions and ambiguous:
            decision = repo.get_active_qualification_decision(conn, group["id"])
            if decision and decision["ranking_snapshot"] == qualification_snapshot(group_result):
                selected = set(json.loads(decision["selected_entry_ids"]))
                for entry in ranked_entries:
                    if entry["player_id"] in selected:
                        entry["qualified"] = True
                group_result["ambiguous_qualification"] = False
                group_result["manually_resolved"] = True
                group_result["qualification_decision"] = _decision_out(decision)
        result.append(group_result)
    return result
