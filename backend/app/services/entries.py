"""统一参赛实体：单打选手、双打组合与团体队伍都通过 Entry 进入比赛。

- SINGLES：1 名成员；DOUBLES：2 名成员；TEAM：>=1 名成员（队伍人数规则属于赛制，未冻结）。
  TEAM 队伍的增删改在 services/teams.py，本模块只负责分支派发与名单确认。
"""

import random
import sqlite3
import time

from .. import repository as repo
from ..models import EventType, MatchStage, MatchStatus, ResultType, TableStatus, TournamentStage
from . import knockout as knockout_service
from . import teams as teams_service
from .transaction import TransactionBusyError, write_transaction


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


def _random_pair_doubles_locked(
    conn: sqlite3.Connection,
    tournament_id: int,
    pairing_seed: int | None = None,
) -> tuple[list[dict], list[dict], int]:
    tournament = _tournament(conn, tournament_id)
    if tournament["event_type"] != EventType.DOUBLES.value:
        raise EntryError("只有双打项目需要随机生成搭档（团体赛的队伍名单请用队伍接口维护）")
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

    return repo.list_entries(conn, tournament_id), remaining, seed


def _confirm_roster_locked(conn: sqlite3.Connection, tournament_id: int) -> tuple[dict, list[dict]]:
    """确认名单。三个项目分支必须显式写全，禁止"非单打即双打"的二元假设。"""
    tournament = _tournament(conn, tournament_id)
    event_type = tournament["event_type"]
    if event_type == EventType.TEAM.value:
        # 名单工作表与普通队伍 CRUD 共用此写锁。验证和冻结必须位于同一
        # 临界区，否则另一个保存请求可能在二者之间改写已验证的名单。
        with teams_service._roster_write_tx(conn):
            tournament = _tournament(conn, tournament_id)
            teams_service.validate_team_roster(conn, tournament_id)
            repo.confirm_tournament_roster(conn, tournament_id)
            result = (repo.get_tournament(conn, tournament_id), repo.list_entries(conn, tournament_id))
        return result
    if event_type == EventType.SINGLES.value:
        build_singles_entries(conn, tournament_id)
    elif event_type == EventType.DOUBLES.value:
        entries = repo.list_entries(conn, tournament_id)
        players = repo.list_players(conn, tournament_id)
        paired_ids = {member["player_id"] for entry in entries for member in entry["members"]}
        if len(paired_ids) != len(players) or any(len(e["members"]) != 2 for e in entries):
            raise EntryError("仍有运动员未完成双打配对，不能确认名单")
    else:
        raise EntryError(f"未知的参赛项目：{event_type}，不能确认名单", 409)
    repo.confirm_tournament_roster(conn, tournament_id)
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
    repo.mark_match_finished(
        conn,
        match["id"],
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


def resolve_withdrawn_participants(conn: sqlite3.Connection, match: dict) -> bool:
    """签位双方到齐后，自动处理其中恰有一方已整项退赛的比赛。"""
    if match["status"] == MatchStatus.FINISHED.value:
        return False
    a, b = match.get("entry_a_id"), match.get("entry_b_id")
    if a is None or b is None:
        return False
    withdrawn = [
        entry for entry_id in (a, b)
        if (entry := repo.get_entry(conn, entry_id)) is not None
        and entry["status"] == "WITHDRAWN"
    ]
    if len(withdrawn) != 1:
        # 双方退赛没有竞技胜者，继续交由主裁特殊处理。
        return False
    entry = withdrawn[0]
    return _forfeit_unfinished_match(
        conn,
        match,
        entry["id"],
        entry.get("withdrawal_reason") or "已退出赛事",
    )


def _withdraw_from_tournament_locked(
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
    if entry["group_id"] is not None:
        repo.invalidate_qualification_decision(
            conn, entry["group_id"], "参赛位已退出赛事"
        )
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
    # A4 尚未合入的 standalone 环境会因缺少 format_code 自动 no-op；组合环境中
    # 则把退赛自动判负后的循环赛完成态与赛事阶段保持在同一事务内。
    from . import formats as formats_service

    formats_service.sync_round_robin_stage(conn, tournament_id)
    return repo.get_entry(conn, entry_id), affected, finished_before

def random_pair_doubles(
    conn: sqlite3.Connection,
    tournament_id: int,
    pairing_seed: int | None = None,
) -> tuple[list[dict], list[dict], int]:
    """名单读取、配对计算、清空旧 Entry 与新 Entry 落库在同一写锁内。"""
    try:
        with write_transaction(conn, busy_message="双打配对繁忙，请稍后重试"):
            return _random_pair_doubles_locked(conn, tournament_id, pairing_seed)
    except TransactionBusyError as exc:
        raise EntryError(str(exc), exc.code) from None


def confirm_roster(conn: sqlite3.Connection, tournament_id: int) -> tuple[dict, list[dict]]:
    """单人/双人名单确认使用统一写锁；团体分支复用既有名单写锁。"""
    tournament = _tournament(conn, tournament_id)
    if tournament["event_type"] == EventType.TEAM.value:
        return _confirm_roster_locked(conn, tournament_id)
    try:
        with write_transaction(conn, busy_message="名单确认繁忙，请稍后重试"):
            return _confirm_roster_locked(conn, tournament_id)
    except TransactionBusyError as exc:
        raise EntryError(str(exc), exc.code) from None


def withdraw_from_tournament(
    conn: sqlite3.Connection,
    tournament_id: int,
    entry_id: int,
    operator_name: str,
    reason: str,
) -> tuple[dict, list[int], int]:
    """退赛状态、自动判负、晋级同步与阶段同步整体提交或回滚。"""
    try:
        with write_transaction(conn, busy_message="退赛办理繁忙，请稍后重试"):
            return _withdraw_from_tournament_locked(
                conn, tournament_id, entry_id, operator_name, reason
            )
    except TransactionBusyError as exc:
        raise EntryError(str(exc), exc.code) from None
