"""比赛生成服务：小组循环赛生成。"""

import random
import sqlite3

from .. import repository as repo
from ..domain import round_robin
from ..models import MatchStage, MatchStatus, TournamentStage
from . import scores as scores_service


class TournamentNotFoundError(Exception):
    pass


class TournamentStageError(Exception):
    pass


class NoGroupsError(Exception):
    pass


class MatchesExistError(Exception):
    pass


def generate_group_matches(
    conn: sqlite3.Connection, tournament_id: int
) -> tuple[int, dict[str, int]]:
    """为所有小组生成单循环比赛（同一事务），赛事进入 GROUP_STAGE。

    返回 (总场数, {组名: 场数})。
    守卫：赛事必须存在、处于 REGISTRATION 阶段、已分组、且尚未生成过小组赛。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TournamentNotFoundError("赛事不存在")
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise TournamentStageError("当前阶段不允许生成小组比赛")
    groups = repo.list_groups(conn, tournament_id)
    if not groups:
        raise NoGroupsError("请先完成自动分组，再生成小组比赛")
    if repo.count_matches(conn, tournament_id, stage=MatchStage.GROUP.value) > 0:
        raise MatchesExistError("小组比赛已生成，不能重复生成")

    entries = [
        entry for entry in repo.list_entries(conn, tournament_id)
        if entry["status"] == "ACTIVE"
    ]
    by_group: dict[int, list[int]] = {}
    for entry in entries:
        if entry["group_id"] is not None:
            by_group.setdefault(entry["group_id"], []).append(entry["id"])
    entry_by_id = {e["id"]: e for e in entries}

    total = 0
    per_group: dict[str, int] = {}
    for group in groups:
        member_ids = by_group.get(group["id"], [])
        schedule = round_robin.round_robin(member_ids)
        per_group[group["name"]] = len(schedule)
        for round_num, a, b in schedule:
            ea, eb = entry_by_id[a], entry_by_id[b]
            player_a = ea["members"][0]["player_id"] if ea["entry_type"] == "SINGLES" else None
            player_b = eb["members"][0]["player_id"] if eb["entry_type"] == "SINGLES" else None
            repo.create_match(
                conn,
                tournament_id,
                MatchStage.GROUP.value,
                group["id"],
                round_num,
                None,
                player_a,
                player_b,
                entry_a_id=a,
                entry_b_id=b,
                bracket="GROUP",
            )
        total += len(schedule)

    repo.update_tournament_stage(conn, tournament_id, TournamentStage.GROUP_STAGE.value)
    conn.commit()
    return total, per_group


DEMO_SCORE_OPTIONS = [(2, 0), (2, 1), (0, 2), (1, 2)]


def finish_group_stage(
    conn: sqlite3.Connection, tournament_id: int, rng: random.Random | None = None
) -> int:
    """Demo：模拟完成所有未结束的小组赛（复用真实 record_score 逻辑，随机非平局比分）。

    返回本次模拟结束的场数。仅 GROUP_STAGE 阶段可用。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TournamentNotFoundError("赛事不存在")
    if tournament["stage"] != TournamentStage.GROUP_STAGE.value:
        raise TournamentStageError("仅小组赛阶段可模拟完成剩余小组赛")

    matches = repo.list_matches(conn, tournament_id, stage=MatchStage.GROUP.value)
    unfinished = [m for m in matches if m["status"] != MatchStatus.FINISHED.value]
    rng = rng or random.Random()
    for m in unfinished:
        sa, sb = rng.choice(DEMO_SCORE_OPTIONS)
        scores_service.record_score(conn, m["id"], sa, sb)
    return len(unfinished)
