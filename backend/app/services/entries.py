"""统一参赛实体：单打选手与双打组合都通过 Entry 进入比赛。"""

import random
import sqlite3
import time

from .. import repository as repo
from ..models import EventType, TournamentStage


class EntryError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise EntryError("赛事不存在", 404)
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise EntryError("赛事已开始，参赛名单已锁定")
    return tournament


def list_entries(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    if repo.get_tournament(conn, tournament_id) is None:
        raise EntryError("赛事不存在", 404)
    return repo.list_entries(conn, tournament_id)


def build_singles_entries(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    players = repo.list_players(conn, tournament_id)
    if len(players) < 2:
        raise EntryError("至少需要 2 名运动员才能确认名单")
    repo.clear_entries(conn, tournament_id)
    for player in players:
        repo.create_entry(
            conn,
            tournament_id,
            EventType.SINGLES.value,
            player["name"],
            player["rating_points"],
            [player["id"]],
            seed_no=player["seed_no"],
        )
    return repo.list_entries(conn, tournament_id)


def random_pair_doubles(
    conn: sqlite3.Connection,
    tournament_id: int,
    pairing_seed: int | None = None,
) -> tuple[list[dict], list[dict], int]:
    tournament = _tournament(conn, tournament_id)
    if tournament["event_type"] != EventType.DOUBLES.value:
        raise EntryError("只有双打项目需要生成搭档")
    players = repo.list_players(conn, tournament_id)
    if len(players) < 4:
        raise EntryError("双打项目至少需要 4 名运动员")

    seed = pairing_seed if pairing_seed is not None else int(time.time_ns() % 2_147_483_647)
    rng = random.Random(seed)
    remaining = sorted(players, key=lambda p: (-p["rating_points"], p["id"]))
    pairs: list[tuple[dict, dict]] = []

    while len(remaining) >= 2:
        first = remaining.pop(0)
        by_distance = sorted(
            remaining,
            key=lambda p: (abs(p["rating_points"] - first["rating_points"]), rng.random()),
        )
        nearby = by_distance[: min(4, len(by_distance))]
        different_affiliation = [
            p for p in nearby if first.get("college") and p.get("college") != first.get("college")
        ]
        candidates = different_affiliation or nearby
        second = rng.choice(candidates)
        remaining.remove(second)
        pairs.append((first, second))

    repo.clear_entries(conn, tournament_id)
    for index, (a, b) in enumerate(pairs, start=1):
        repo.create_entry(
            conn,
            tournament_id,
            EventType.DOUBLES.value,
            f"{a['name']} / {b['name']}",
            a["rating_points"] + b["rating_points"],
            [a["id"], b["id"]],
            seed_no=index if index <= tournament["group_count"] else None,
        )

    conn.commit()
    return repo.list_entries(conn, tournament_id), remaining, seed


def confirm_roster(conn: sqlite3.Connection, tournament_id: int) -> tuple[dict, list[dict]]:
    tournament = _tournament(conn, tournament_id)
    if tournament["event_type"] == EventType.SINGLES.value:
        build_singles_entries(conn, tournament_id)
    else:
        entries = repo.list_entries(conn, tournament_id)
        players = repo.list_players(conn, tournament_id)
        paired_ids = {member["player_id"] for entry in entries for member in entry["members"]}
        if len(paired_ids) != len(players) or any(len(e["members"]) != 2 for e in entries):
            raise EntryError("仍有运动员未完成双打配对，不能确认名单")
    repo.confirm_tournament_roster(conn, tournament_id)
    conn.commit()
    return repo.get_tournament(conn, tournament_id), repo.list_entries(conn, tournament_id)
