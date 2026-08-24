"""淘汰赛服务：晋级校验、bracket 生成、胜者晋级、改分级联重置、树查询。"""

import sqlite3

from .. import repository as repo
from ..domain import knockout
from ..models import MatchStage, MatchStatus, TableStatus, TournamentStage
from . import rankings as rankings_service


class KnockoutError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _ensure_tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise KnockoutError("赛事不存在", 404)
    return tournament


def generate_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """所有小组结束后，按每组前 N 名自动晋级并生成交叉淘汰赛。"""
    tournament = _ensure_tournament(conn, tournament_id)
    if tournament["stage"] != TournamentStage.GROUP_STAGE.value:
        raise KnockoutError("当前阶段不允许生成淘汰赛")
    if repo.count_matches(conn, tournament_id, stage=MatchStage.KNOCKOUT.value) > 0:
        raise KnockoutError("淘汰赛已生成，不能重复生成")

    rankings = rankings_service.get_rankings(conn, tournament_id)
    for g in rankings:
        if g["finished_matches"] < g["total_matches"]:
            raise KnockoutError(f"{g['group_name']} 小组赛尚未全部结束（{g['finished_matches']}/{g['total_matches']}）")
        if g["ambiguous_qualification"]:
            raise KnockoutError(f"{g['group_name']} 存在无法判定的并列晋级，请先人工裁决")

    qualifiers_by_group = [
        [e["player_id"] for e in g["entries"] if e["qualified"]] for g in rankings
    ]
    try:
        rounds_spec = knockout.build_bracket(qualifiers_by_group)
    except ValueError as exc:
        raise KnockoutError(str(exc))

    # 落库：首轮带选手；后续轮次为空槽位，prev 指向上一轮对应比赛
    id_by_position: dict[tuple[int, int], int] = {}
    for round_spec in rounds_spec:
        for spec in round_spec:
            r, idx = spec["round"], spec["match_index"]
            prev_a = id_by_position.get((r - 1, idx * 2))
            prev_b = id_by_position.get((r - 1, idx * 2 + 1))
            match = repo.create_match(
                conn,
                tournament_id,
                MatchStage.KNOCKOUT.value,
                None,
                r,
                idx,
                spec["player_a_id"],
                spec["player_b_id"],
                prev_match_a_id=prev_a,
                prev_match_b_id=prev_b,
            )
            id_by_position[(r, idx)] = match["id"]

    repo.update_tournament_stage(conn, tournament_id, TournamentStage.KNOCKOUT.value)
    conn.commit()
    return get_knockout(conn, tournament_id)


# ------------------------------------------------------------------ 胜者晋级

def advance_winner(conn: sqlite3.Connection, match: dict) -> None:
    """把已结束比赛的胜者填入下一轮对应槽位。"""
    if match["stage"] != MatchStage.KNOCKOUT.value or match["winner_id"] is None:
        return
    for nm in repo.list_matches_by_prev(conn, match["id"]):
        if nm["prev_match_a_id"] == match["id"]:
            repo.update_match(conn, nm["id"], player_a_id=match["winner_id"])
        elif nm["prev_match_b_id"] == match["id"]:
            repo.update_match(conn, nm["id"], player_b_id=match["winner_id"])


def reset_branch(conn: sqlite3.Connection, match_id: int) -> None:
    """改分时把以本比赛为来源的整条下游链重置（递归）。

    - 下游比赛清空状态/比分/胜者/来源槽位，释放球台；
    - 未被本次修改影响的另一槽位选手保留。
    """
    for nm in repo.list_matches_by_prev(conn, match_id):
        reset_branch(conn, nm["id"])
        if nm["status"] == MatchStatus.PLAYING.value and nm["table_id"] is not None:
            repo.update_table_status(conn, nm["table_id"], TableStatus.FREE.value)
        keep_a = nm["player_a_id"] if nm["prev_match_a_id"] != match_id else None
        keep_b = nm["player_b_id"] if nm["prev_match_b_id"] != match_id else None
        repo.update_match(
            conn,
            nm["id"],
            status=MatchStatus.WAITING.value,
            table_id=None,
            player_a_id=keep_a,
            player_b_id=keep_b,
            player_a_score=None,
            player_b_score=None,
            winner_id=None,
        )


def sync_stage(conn: sqlite3.Connection, tournament_id: int) -> None:
    """按决赛状态同步赛事阶段（淘汰赛结束后 FINISHED，改分回退 KNOCKOUT）。"""
    knockout_matches = repo.list_matches(conn, tournament_id, stage=MatchStage.KNOCKOUT.value)
    if not knockout_matches:
        return
    max_round = max(m["round"] for m in knockout_matches)
    final = next(m for m in knockout_matches if m["round"] == max_round)
    stage = (
        TournamentStage.FINISHED.value
        if final["status"] == MatchStatus.FINISHED.value
        else TournamentStage.KNOCKOUT.value
    )
    repo.update_tournament_stage(conn, tournament_id, stage)


# ------------------------------------------------------------------ 树查询

def round_label(round_num: int, total_rounds: int) -> str:
    participants = 2 ** (total_rounds - round_num + 1)
    if participants == 2:
        return "决赛"
    if participants == 4:
        return "半决赛"
    return f"{participants}强赛"


def get_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = _ensure_tournament(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id, stage=MatchStage.KNOCKOUT.value)
    players = repo.list_players(conn, tournament_id)
    info_by_id = {p["id"]: {"name": p["name"], "seed_no": p["seed_no"]} for p in players}

    if not matches:
        return {
            "tournament": tournament,
            "rounds": [],
            "champion": None,
            "runner_up": None,
        }

    max_round = max(m["round"] for m in matches)
    by_round: dict[int, list[dict]] = {}
    for m in matches:
        by_round.setdefault(m["round"], []).append(m)

    rounds = []
    for r in range(1, max_round + 1):
        round_matches = sorted(by_round.get(r, []), key=lambda m: m["match_index"])
        rounds.append(
            {
                "round": r,
                "label": round_label(r, max_round),
                "matches": [
                    {
                        "id": m["id"],
                        "round": m["round"],
                        "match_index": m["match_index"],
                        "status": m["status"],
                        "player_a": (
                            {
                                "id": m["player_a_id"],
                                "name": info_by_id.get(m["player_a_id"], {}).get("name"),
                                "seed_no": info_by_id.get(m["player_a_id"], {}).get("seed_no"),
                            }
                            if m["player_a_id"] is not None else None
                        ),
                        "player_b": (
                            {
                                "id": m["player_b_id"],
                                "name": info_by_id.get(m["player_b_id"], {}).get("name"),
                                "seed_no": info_by_id.get(m["player_b_id"], {}).get("seed_no"),
                            }
                            if m["player_b_id"] is not None else None
                        ),
                        "player_a_score": m["player_a_score"],
                        "player_b_score": m["player_b_score"],
                        "winner_id": m["winner_id"],
                        "table_id": m["table_id"],
                        "prev_match_a_id": m["prev_match_a_id"],
                        "prev_match_b_id": m["prev_match_b_id"],
                    }
                    for m in round_matches
                ],
            }
        )

    final = next(m for m in matches if m["round"] == max_round)
    champion = runner_up = None
    if final["status"] == MatchStatus.FINISHED.value and final["winner_id"] is not None:
        loser_id = (
            final["player_b_id"] if final["winner_id"] == final["player_a_id"]
            else final["player_a_id"]
        )
        champion = {
            "id": final["winner_id"],
            "name": info_by_id.get(final["winner_id"], {}).get("name"),
            "seed_no": info_by_id.get(final["winner_id"], {}).get("seed_no"),
        }
        runner_up = {
            "id": loser_id,
            "name": info_by_id.get(loser_id, {}).get("name"),
            "seed_no": info_by_id.get(loser_id, {}).get("seed_no"),
        }

    return {
        "tournament": tournament,
        "rounds": rounds,
        "champion": champion,
        "runner_up": runner_up,
    }
