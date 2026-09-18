"""分组服务：自动分组 / 清空分组 / 查看分组（含成员）。"""

import random
import sqlite3

from .. import repository as repo
from ..models import TournamentStage
from . import entries as entry_service
from . import teams as teams_service


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
    entries = repo.list_entries(conn, tournament_id)

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
                "qualify_count": g["qualify_count"],
                "players": [
                    {"id": m["id"], "name": m["name"], "college": m["college"]}
                    for m in members
                ],
                "entries": [e for e in entries if e["group_id"] == g["id"]],
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
    entries = repo.list_entries(conn, tournament_id)
    if not entries:
        try:
            _, entries = entry_service.confirm_roster(conn, tournament_id)
            tournament = repo.get_tournament(conn, tournament_id)
        except (entry_service.EntryError, teams_service.TeamError) as exc:
            # 团体赛的名单校验住在 services/teams.py，错误类型不同但语义一样：
            # 名单还没准备好就不该分组，统一转成分组阶段错误。
            raise TournamentStageError(str(exc))
    seeded = sorted(
        (e for e in entries if e["seed_no"] is not None), key=lambda e: e["seed_no"]
    )
    # 先确保种子分散，再在人数均衡的候选组里优先选择同单位最少的组。
    # 这是 soft constraint：单位人数超过组数时仍会生成合法分组。
    chooser = rng or random.Random()
    partition: list[list[int]] = [[] for _ in range(tournament["group_count"])]
    affiliation_counts: list[dict[str, int]] = [{} for _ in partition]

    def affiliations(entry: dict) -> set[str]:
        return {m["college"] for m in entry["members"] if m.get("college")}

    def place(entry: dict, index: int) -> None:
        partition[index].append(entry["id"])
        for affiliation in affiliations(entry):
            affiliation_counts[index][affiliation] = affiliation_counts[index].get(affiliation, 0) + 1

    for index, entry in enumerate(seeded[: tournament["group_count"]]):
        place(entry, index)

    seeded_ids = {entry["id"] for entry in seeded}
    remaining = [entry for entry in entries if entry["id"] not in seeded_ids]
    chooser.shuffle(remaining)
    for entry in remaining:
        smallest = min(len(group) for group in partition)
        candidates = [i for i, group in enumerate(partition) if len(group) == smallest]
        own_affiliations = affiliations(entry)
        best_overlap = min(
            sum(affiliation_counts[i].get(a, 0) for a in own_affiliations)
            for i in candidates
        )
        best = [
            i for i in candidates
            if sum(affiliation_counts[i].get(a, 0) for a in own_affiliations) == best_overlap
        ]
        place(entry, chooser.choice(best))

    repo.clear_player_groups(conn, tournament_id)
    repo.clear_entry_groups(conn, tournament_id)
    repo.delete_groups_for_tournament(conn, tournament_id)

    entry_by_id = {e["id"]: e for e in entries}
    for index, member_ids in enumerate(partition):
        group = repo.create_group(conn, tournament_id, group_name(index), index)
        for entry_id in member_ids:
            repo.set_entry_group(conn, entry_id, group["id"])
            for member in entry_by_id[entry_id]["members"]:
                repo.set_player_group(conn, member["player_id"], group["id"])

    conn.commit()
    return get_groups_with_players(conn, tournament_id)


def ungroup_tournament(conn: sqlite3.Connection, tournament_id: int) -> None:
    """清空全部小组（回到未分组状态）。"""
    _ensure_registration(conn, tournament_id)
    repo.clear_player_groups(conn, tournament_id)
    repo.clear_entry_groups(conn, tournament_id)
    repo.delete_groups_for_tournament(conn, tournament_id)
    conn.commit()
