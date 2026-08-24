"""分组服务：自动分组 / 清空分组 / 查看分组（含成员）。"""

import random
import sqlite3

from .. import repository as repo
from ..domain import grouping
from ..models import TournamentStage


class TournamentNotFoundError(Exception):
    pass


class TournamentStageError(Exception):
    pass


def group_name(index: int) -> str:
    """A组、B组、C组……"""
    return f"{chr(ord('A') + index)}组"


def get_groups_with_players(
    conn: sqlite3.Connection, tournament_id: int
) -> list[dict]:
    """返回 [{"id","name","sort_order","players":[{"id","name","college"}]}, ...]。"""
    groups = repo.list_groups(conn, tournament_id)
    players = repo.list_players(conn, tournament_id)

    by_group: dict[int, list[dict]] = {}
    for p in players:
        if p["group_id"] is not None:
            by_group.setdefault(p["group_id"], []).append(p)

    result = []
    for g in groups:
        members = sorted(by_group.get(g["id"], []), key=lambda p: p["id"])
        result.append(
            {
                "id": g["id"],
                "name": g["name"],
                "sort_order": g["sort_order"],
                "players": [
                    {"id": m["id"], "name": m["name"], "college": m["college"]}
                    for m in members
                ],
            }
        )
    return result


def _ensure_registration(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TournamentNotFoundError("赛事不存在")
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise TournamentStageError("赛事已进入比赛阶段，不允许调整分组")
    return tournament


def auto_group_tournament(
    conn: sqlite3.Connection,
    tournament_id: int,
    rng: random.Random | None = None,
) -> list[dict]:
    """自动分组并落库（同一事务）。

    流程：清空旧分组 → 删除旧组 → 按算法重新分配 → 建组并归属选手。
    """
    tournament = _ensure_registration(conn, tournament_id)
    players = repo.list_players(conn, tournament_id)
    ids = [p["id"] for p in players]
    seeded = sorted(
        (p for p in players if p["seed_no"] is not None), key=lambda p: p["seed_no"]
    )
    seeds = [p["id"] for p in seeded]
    partition = grouping.auto_group(ids, tournament["group_count"], rng, seeds)

    repo.clear_player_groups(conn, tournament_id)
    repo.delete_groups_for_tournament(conn, tournament_id)

    for index, member_ids in enumerate(partition):
        group = repo.create_group(conn, tournament_id, group_name(index), index)
        for pid in member_ids:
            repo.set_player_group(conn, pid, group["id"])

    conn.commit()
    return get_groups_with_players(conn, tournament_id)


def ungroup_tournament(conn: sqlite3.Connection, tournament_id: int) -> None:
    """清空全部小组（回到未分组状态）。"""
    _ensure_registration(conn, tournament_id)
    repo.clear_player_groups(conn, tournament_id)
    repo.delete_groups_for_tournament(conn, tournament_id)
    conn.commit()
