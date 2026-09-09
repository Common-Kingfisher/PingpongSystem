"""统一参赛实体：单打选手与双打组合都通过 Entry 进入比赛。"""

import random
import sqlite3
import time

from .. import repository as repo
from ..models import EventType, MatchStage, MatchStatus, ResultType, TableStatus, TournamentStage
from . import knockout as knockout_service


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


def _entry_player_id(conn: sqlite3.Connection, entry_id: int | None) -> int | None:
    if entry_id is None:
        return None
    entry = repo.get_entry(conn, entry_id)
    if entry and entry["entry_type"] == EventType.SINGLES.value and entry["members"]:
        return entry["members"][0]["player_id"]
    return None


def _forfeit_unfinished_match(
    conn: sqlite3.Connection, match: dict, withdrawn_entry_id: int, reason: str
) -> bool:
    a, b = match.get("entry_a_id"), match.get("entry_b_id")
    if match["status"] == MatchStatus.FINISHED.value or withdrawn_entry_id not in (a, b):
        return False
    opponent = b if withdrawn_entry_id == a else a
    if opponent is None:
        return False
    opponent_entry = repo.get_entry(conn, opponent)
    if opponent_entry is None or opponent_entry["status"] == "WITHDRAWN":
        # 双方均退赛没有竞技意义上的胜者，保留给主裁判特殊处理。
        return False

    tournament = repo.get_tournament(conn, match["tournament_id"])
    if match["stage"] == MatchStage.GROUP.value:
        score_a = 0 if withdrawn_entry_id == a else tournament["games_to_win"]
        score_b = 0 if withdrawn_entry_id == b else tournament["games_to_win"]
    else:
        score_a = score_b = 0
    if match.get("table_id") is not None:
        repo.update_table_status(conn, match["table_id"], TableStatus.FREE.value)
    repo.replace_match_games(conn, match["id"], [], a, b)
    repo.update_match(
        conn,
        match["id"],
        status=MatchStatus.FINISHED.value,
        table_id=None,
        player_a_score=score_a,
        player_b_score=score_b,
        winner_id=_entry_player_id(conn, opponent),
        winner_entry_id=opponent,
        result_type=ResultType.FORFEIT.value,
        forfeit_entry_id=withdrawn_entry_id,
        result_note=f"整项退赛：{reason}",
    )
    if match["group_id"] is not None:
        repo.invalidate_qualification_decision(conn, match["group_id"], "参赛位已退出赛事")
    if match["stage"] == MatchStage.KNOCKOUT.value:
        knockout_service.advance_winner(conn, repo.get_match(conn, match["id"]))
    return True


def withdraw_from_tournament(
    conn: sqlite3.Connection,
    tournament_id: int,
    entry_id: int,
    operator_name: str,
    reason: str,
) -> tuple[dict, list[int], int]:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise EntryError("赛事不存在", 404)
    if tournament["stage"] == TournamentStage.FINISHED.value:
        raise EntryError("赛事已经结束，不能再办理退赛")
    entry = repo.get_entry(conn, entry_id)
    if entry is None or entry["tournament_id"] != tournament_id:
        raise EntryError("参赛位不存在", 404)
    if entry["status"] == "WITHDRAWN":
        raise EntryError("该参赛位已经退出赛事")

    operator = operator_name.strip()
    cleaned_reason = reason.strip()
    if not operator:
        raise EntryError("请输入主裁判姓名", 422)
    if len(cleaned_reason) < 2:
        raise EntryError("请填写至少 2 个字的退赛原因", 422)

    repo.withdraw_entry(conn, entry_id, operator, cleaned_reason)
    finished_before = sum(
        1 for match in repo.list_matches(conn, tournament_id)
        if match["status"] == MatchStatus.FINISHED.value
        and entry_id in (match.get("entry_a_id"), match.get("entry_b_id"))
    )
    affected: list[int] = []
    # 淘汰晋级会在循环中填充下一场签位，因此每轮重新读取，直到没有新场次可判。
    while True:
        changed = False
        for match in repo.list_matches(conn, tournament_id):
            if match["id"] in affected:
                continue
            if _forfeit_unfinished_match(conn, match, entry_id, cleaned_reason):
                affected.append(match["id"])
                changed = True
        if not changed:
            break
    if any(
        match["stage"] == MatchStage.KNOCKOUT.value
        for match in repo.list_matches(conn, tournament_id)
    ):
        knockout_service.sync_stage(conn, tournament_id)
    conn.commit()
    return repo.get_entry(conn, entry_id), affected, finished_before
