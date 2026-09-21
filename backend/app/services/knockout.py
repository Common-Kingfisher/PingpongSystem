"""单败主签、名次排位与冠军路径。兼容旧 player 字段并优先使用 Entry。"""

import sqlite3

from .. import repository as repo
from ..domain import knockout
from ..models import (
    BronzeMode,
    EventType,
    MatchBracket,
    MatchStage,
    MatchStatus,
    PlacementMode,
    ResultType,
    TableStatus,
    TournamentStage,
)
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


def _entry_player_id(conn: sqlite3.Connection, entry_id: int | None) -> int | None:
    if entry_id is None:
        return None
    entry = repo.get_entry(conn, entry_id)
    if entry and entry["entry_type"] == "SINGLES" and entry["members"]:
        return entry["members"][0]["player_id"]
    return None


def _side(match: dict, side: str) -> int | None:
    return match.get(f"entry_{side}_id") or match.get(f"player_{side}_id")


def _winner(match: dict) -> int | None:
    return match.get("winner_entry_id") or match.get("winner_id")


def _loser(match: dict) -> int | None:
    winner = _winner(match)
    a, b = _side(match, "a"), _side(match, "b")
    if winner is None or a is None or b is None:
        return None
    return b if winner == a else a


def _create_bracket(
    conn: sqlite3.Connection,
    tournament_id: int,
    participant_ids: list[int],
    bracket: str,
    placement_min: int | None = None,
    placement_max: int | None = None,
    loser_source_by_entry: dict[int, int] | None = None,
) -> None:
    rounds_spec = knockout.build_bracket([participant_ids], allow_extended=True)
    id_by_position: dict[tuple[int, int], int] = {}
    created_match_ids: list[int] = []
    for round_spec in rounds_spec:
        for spec in round_spec:
            round_no, index = spec["round"], spec["match_index"]
            a, b = spec["player_a_id"], spec["player_b_id"]
            if round_no == 1 and loser_source_by_entry:
                prev_a = loser_source_by_entry.get(a) if a is not None else None
                prev_b = loser_source_by_entry.get(b) if b is not None else None
                outcome_a = outcome_b = "LOSER"
            else:
                prev_a = id_by_position.get((round_no - 1, index * 2))
                prev_b = id_by_position.get((round_no - 1, index * 2 + 1))
                outcome_a = outcome_b = "WINNER"
            match = repo.create_match(
                conn,
                tournament_id,
                MatchStage.KNOCKOUT.value,
                None,
                round_no,
                index,
                _entry_player_id(conn, a),
                _entry_player_id(conn, b),
                prev_match_a_id=prev_a,
                prev_match_b_id=prev_b,
                prev_match_a_outcome=outcome_a,
                prev_match_b_outcome=outcome_b,
                entry_a_id=a,
                entry_b_id=b,
                bracket=bracket,
                placement_min=placement_min,
                placement_max=placement_max,
            )
            id_by_position[(round_no, index)] = match["id"]
            created_match_ids.append(match["id"])

    # 名次赛/季军赛是在源比赛结束后动态创建的。退赛者可能在新场次创建前
    # 已经退出，因而不会被 withdraw_from_tournament() 当时的扫描命中。
    # 必须等整棵依赖签位建立完成后统一补判，确保自动晋级还能沿下游传播。
    from . import entries as entry_service
    for match_id in created_match_ids:
        entry_service.resolve_withdrawn_participants(
            conn, repo.get_match(conn, match_id)
        )


def prepare_knockout_generation(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """只读校验并准备淘汰签表生成所需数据。

    此函数是淘汰赛生成前置条件的单一来源：既供真正的写库生成路径使用，
    也供赛制 Handler 查询“能否推进”。它绝不创建比赛、更新阶段或提交事务。
    """
    tournament = _ensure_tournament(conn, tournament_id)
    if tournament["event_type"] == EventType.TEAM.value:
        raise KnockoutError("团体赛不生成单打式淘汰赛：团体对阵请使用团体对抗（TeamTie）接口")
    if tournament["stage"] != TournamentStage.GROUP_STAGE.value:
        raise KnockoutError("当前阶段不允许生成淘汰赛")
    existing = repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
    if any(m["bracket"] == MatchBracket.MAIN.value for m in existing):
        raise KnockoutError("淘汰赛已生成，不能重复生成")

    rankings = rankings_service.get_rankings(conn, tournament_id)
    for group in rankings:
        if group["finished_matches"] < group["total_matches"]:
            raise KnockoutError(
                f"{group['group_name']} 小组赛尚未全部结束（{group['finished_matches']}/{group['total_matches']}）"
            )
        if group["ambiguous_qualification"]:
            raise KnockoutError(f"{group['group_name']} 存在无法判定的并列晋级，请先人工裁决")

    qualifiers_by_group = [
        [entry["player_id"] for entry in group["entries"] if entry["qualified"]]
        for group in rankings
    ]
    try:
        rounds_spec = knockout.build_bracket(qualifiers_by_group, allow_extended=True)
    except ValueError as exc:
        raise KnockoutError(str(exc)) from exc

    return {
        "tournament": tournament,
        "rankings": rankings,
        "qualifiers_by_group": qualifiers_by_group,
        "rounds_spec": rounds_spec,
    }


def generate_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    prepared = prepare_knockout_generation(conn, tournament_id)
    tournament = prepared["tournament"]
    rounds_spec = prepared["rounds_spec"]

    id_by_position: dict[tuple[int, int], int] = {}
    for round_spec in rounds_spec:
        for spec in round_spec:
            r, idx = spec["round"], spec["match_index"]
            a, b = spec["player_a_id"], spec["player_b_id"]
            match = repo.create_match(
                conn,
                tournament_id,
                MatchStage.KNOCKOUT.value,
                None,
                r,
                idx,
                _entry_player_id(conn, a),
                _entry_player_id(conn, b),
                prev_match_a_id=id_by_position.get((r - 1, idx * 2)),
                prev_match_b_id=id_by_position.get((r - 1, idx * 2 + 1)),
                entry_a_id=a,
                entry_b_id=b,
                bracket=MatchBracket.MAIN.value,
            )
            id_by_position[(r, idx)] = match["id"]

    # 轮空立即晋级，但不计真实胜场。
    for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value):
        if match["bracket"] != MatchBracket.MAIN.value or match["round"] != 1:
            continue
        a, b = _side(match, "a"), _side(match, "b")
        if (a is None) != (b is None):
            winner = a or b
            repo.update_match(
                conn,
                match["id"],
                status=MatchStatus.FINISHED.value,
                player_a_score=0,
                player_b_score=0,
                winner_id=_entry_player_id(conn, winner),
                winner_entry_id=winner,
                result_type=ResultType.WALKOVER.value,
            )
            advance_winner(conn, repo.get_match(conn, match["id"]))

    repo.update_tournament_stage(conn, tournament_id, TournamentStage.KNOCKOUT.value)
    conn.commit()
    return get_knockout(conn, tournament_id)


def _has_real_result(conn: sqlite3.Connection, match: dict) -> bool:
    """判断淘汰赛比赛是否已经产生"真实"结果（轮空自动晋级不算）。

    轮空由系统在生成签表时写入（一方为空、WALKOVER、0:0），它不代表任何真实比赛，
    撤销签表时应当连同签表一起消失；一旦双方就位并开赛/录分，就属于真实结果，禁止静默删除。
    """
    if match["status"] == MatchStatus.PLAYING.value:
        return True
    side_a, side_b = _side(match, "a"), _side(match, "b")
    if side_a is None or side_b is None:
        return False
    if match["status"] == MatchStatus.FINISHED.value:
        return True
    return any(
        match.get(field) is not None
        for field in (
            "player_a_score",
            "player_b_score",
            "winner_id",
            "winner_entry_id",
            "result_type",
        )
    )


def undo_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """撤销淘汰签表：删除 KNOCKOUT / PLACEMENT 比赛，让小组结果重新可修正。

    安全策略：
      - 尚未生成淘汰赛 → 409；
      - 淘汰赛已经开始（存在 PLAYING、或双方就位的 FINISHED / 已录比分）→ 409，不静默删除；
      - 系统轮空（一方为空 + WALKOVER）不算真实结果，允许随签表一起撤销。
    只删除淘汰阶段派生数据，不动选手、分组、小组比赛与小组比分。
    """
    _ensure_tournament(conn, tournament_id)
    knockout_matches = repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
    main_matches = [m for m in knockout_matches if m["bracket"] == MatchBracket.MAIN.value]
    if not main_matches:
        raise KnockoutError("尚未生成淘汰赛，无需撤销")

    for match in knockout_matches:
        if _has_real_result(conn, match):
            raise KnockoutError("淘汰赛已经开始，不能直接撤销。")

    # 先删名次排位（其来源指向主签），再按轮次从后往前删主签，避免 prev_match 外键冲突。
    ordered = sorted(
        knockout_matches,
        key=lambda m: (
            0 if m["bracket"] == MatchBracket.PLACEMENT.value else 1,
            -(m["round"] or 0),
        ),
    )
    deleted_placement = 0
    deleted_main = 0
    for match in ordered:
        if match["table_id"] is not None:
            # 未开始的比赛不应占用球台；防御性释放，保持"PLAYING 数 == OCCUPIED 数"。
            repo.update_table_status(conn, match["table_id"], TableStatus.FREE.value)
        repo.delete_match(conn, match["id"])
        if match["bracket"] == MatchBracket.PLACEMENT.value:
            deleted_placement += 1
        else:
            deleted_main += 1

    # 淘汰赛只能从 GROUP_STAGE 成功生成；即使每组只有一人、合法地没有任何
    # GROUP 比赛，撤销后也必须回到同一阶段，以允许重新检查并再次生成签表。
    repo.update_tournament_stage(conn, tournament_id, TournamentStage.GROUP_STAGE.value)
    conn.commit()
    return {
        "tournament": repo.get_tournament(conn, tournament_id),
        "deleted_main_matches": deleted_main,
        "deleted_placement_matches": deleted_placement,
        "deleted_matches": deleted_main + deleted_placement,
    }


def advance_winner(conn: sqlite3.Connection, match: dict) -> None:
    """把本场胜者/负者同步到所有声明依赖的后续签位。"""
    if match["stage"] != MatchStage.KNOCKOUT.value:
        return
    winner, loser = _winner(match), _loser(match)
    if winner is None:
        return
    for next_match in repo.list_matches_by_prev(conn, match["id"]):
        if next_match["prev_match_a_id"] == match["id"]:
            participant = loser if next_match.get("prev_match_a_outcome", "WINNER") == "LOSER" else winner
            repo.update_match(conn, next_match["id"], entry_a_id=participant, player_a_id=_entry_player_id(conn, participant))
        elif next_match["prev_match_b_id"] == match["id"]:
            participant = loser if next_match.get("prev_match_b_outcome", "WINNER") == "LOSER" else winner
            repo.update_match(conn, next_match["id"], entry_b_id=participant, player_b_id=_entry_player_id(conn, participant))
        # 对手可能早已退赛且此前另一侧仍待定；签位刚补齐时必须立即补判。
        from . import entries as entry_service
        entry_service.resolve_withdrawn_participants(
            conn, repo.get_match(conn, next_match["id"])
        )


def _create_loser_bracket(
    conn: sqlite3.Connection,
    tournament_id: int,
    source_matches: list[dict],
    placement_min: int,
    placement_max: int,
) -> None:
    """Create an independent classification bracket from finished-match losers."""
    losers = [_loser(match) for match in source_matches]
    if any(entry_id is None for entry_id in losers):
        return
    loser_ids = [entry_id for entry_id in losers if entry_id is not None]
    loser_sources = {
        entry_id: match["id"] for entry_id, match in zip(loser_ids, source_matches)
    }
    _create_bracket(
        conn,
        tournament_id,
        loser_ids,
        MatchBracket.PLACEMENT.value,
        placement_min,
        placement_max,
        loser_sources,
    )


def ensure_placement_matches(conn: sqlite3.Connection, tournament_id: int) -> None:
    tournament = _ensure_tournament(conn, tournament_id)
    all_matches = repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
    main = [m for m in all_matches if m["bracket"] == MatchBracket.MAIN.value]
    if not main:
        return
    max_round = max(m["round"] for m in main)

    semis = [m for m in main if m["round"] == max_round - 1]
    existing_34 = [m for m in all_matches if m.get("placement_min") == 3 and m.get("placement_max") == 4]
    if (
        tournament["bronze_mode"] == BronzeMode.BRONZE_MATCH.value
        and len(semis) == 2
        and all(m["status"] == MatchStatus.FINISHED.value for m in semis)
        and not existing_34
    ):
        _create_loser_bracket(conn, tournament_id, semis, 3, 4)

    if tournament["placement_mode"] != PlacementMode.COMPLETE.value:
        return

    # Every completed main-bracket round before the semifinals starts an
    # independent classification band. A 16-entry draw therefore creates
    # 9–16 from round-one losers and 5–8 from quarterfinal losers.
    bracket_size = len([m for m in main if m["round"] == 1]) * 2
    if bracket_size > 16:
        return
    for round_no in range(1, max_round - 1):
        source_matches = sorted(
            [m for m in main if m["round"] == round_no],
            key=lambda match: match["match_index"] or 0,
        )
        placement_min = bracket_size // (2 ** round_no) + 1
        placement_max = bracket_size // (2 ** (round_no - 1))
        expected = placement_max - placement_min + 1
        existing = [
            m for m in all_matches
            if m.get("placement_min") == placement_min
            and m.get("placement_max") == placement_max
        ]
        real_sources = [
            m for m in source_matches
            if _side(m, "a") is not None and _side(m, "b") is not None
        ]
        if (
            not existing
            and len(real_sources) == expected
            and all(m["status"] == MatchStatus.FINISHED.value for m in source_matches)
        ):
            _create_loser_bracket(
                conn, tournament_id, real_sources, placement_min, placement_max
            )

    # Recursively classify losers inside every existing placement band. For
    # example, 9–16 produces 13–16 and 11–12; 13–16 then produces 15–16.
    all_matches = repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
    bands = {
        (m["placement_min"], m["placement_max"])
        for m in all_matches
        if m["bracket"] == MatchBracket.PLACEMENT.value
        and m.get("placement_min") is not None
        and m.get("placement_max") is not None
        and m["placement_min"] >= 5
    }
    for placement_min, placement_max in sorted(bands):
        size = placement_max - placement_min + 1
        if size < 4 or size & (size - 1):
            continue
        rounds = size.bit_length() - 1
        band_matches = [
            m for m in all_matches
            if m.get("placement_min") == placement_min
            and m.get("placement_max") == placement_max
        ]
        for round_no in range(1, rounds):
            source_matches = sorted(
                [m for m in band_matches if m["round"] == round_no],
                key=lambda match: match["match_index"] or 0,
            )
            child_min = placement_min + size // (2 ** round_no)
            child_max = placement_min + size // (2 ** (round_no - 1)) - 1
            child_exists = any(
                m.get("placement_min") == child_min
                and m.get("placement_max") == child_max
                for m in all_matches
            )
            if (
                source_matches
                and not child_exists
                and len(source_matches) == child_max - child_min + 1
                and all(m["status"] == MatchStatus.FINISHED.value for m in source_matches)
            ):
                _create_loser_bracket(
                    conn, tournament_id, source_matches, child_min, child_max
                )


def descendants(conn: sqlite3.Connection, match_id: int) -> list[dict]:
    """返回所有直接和间接下游比赛，包含胜者线与负者排位线。"""
    result: list[dict] = []
    seen: set[int] = set()
    stack = repo.list_matches_by_prev(conn, match_id)
    while stack:
        match = stack.pop()
        if match["id"] in seen:
            continue
        seen.add(match["id"])
        result.append(match)
        stack.extend(repo.list_matches_by_prev(conn, match["id"]))
    return result


def reset_branch(conn: sqlite3.Connection, match_id: int) -> None:
    for next_match in repo.list_matches_by_prev(conn, match_id):
        reset_branch(conn, next_match["id"])
        if next_match["status"] == MatchStatus.PLAYING.value and next_match["table_id"] is not None:
            repo.update_table_status(conn, next_match["table_id"], TableStatus.FREE.value)
        keep_a = next_match["entry_a_id"] if next_match["prev_match_a_id"] != match_id else None
        keep_b = next_match["entry_b_id"] if next_match["prev_match_b_id"] != match_id else None
        repo.update_match(
            conn,
            next_match["id"],
            status=MatchStatus.WAITING.value,
            table_id=None,
            entry_a_id=keep_a,
            entry_b_id=keep_b,
            player_a_id=_entry_player_id(conn, keep_a),
            player_b_id=_entry_player_id(conn, keep_b),
            player_a_score=None,
            player_b_score=None,
            winner_id=None,
            winner_entry_id=None,
            result_type=None,
            forfeit_entry_id=None,
        )


def sync_stage(conn: sqlite3.Connection, tournament_id: int) -> None:
    ensure_placement_matches(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
    main = [m for m in matches if m["bracket"] == MatchBracket.MAIN.value]
    if not main:
        return
    main_final = max(main, key=lambda m: m["round"])
    placements = [m for m in matches if m["bracket"] == MatchBracket.PLACEMENT.value]
    complete = main_final["status"] == MatchStatus.FINISHED.value and all(
        m["status"] == MatchStatus.FINISHED.value for m in placements
    )
    repo.update_tournament_stage(
        conn,
        tournament_id,
        TournamentStage.FINISHED.value if complete else TournamentStage.KNOCKOUT.value,
    )


def round_label(round_num: int, total_rounds: int) -> str:
    participants = 2 ** (total_rounds - round_num + 1)
    if participants == 2:
        return "决赛"
    if participants == 4:
        return "半决赛"
    return f"{participants}强赛"


def _brief(conn: sqlite3.Connection, participant_id: int | None) -> dict | None:
    if participant_id is None:
        return None
    entry = repo.get_entry(conn, participant_id)
    if entry:
        return {
            "id": entry["id"],
            "name": entry["display_name"],
            "seed_no": entry["seed_no"],
            "member_names": [m["name"] for m in entry["members"]],
        }
    player = repo.get_player(conn, participant_id)
    if not player:
        return None
    return {"id": player["id"], "name": player["name"], "seed_no": player["seed_no"], "member_names": [player["name"]]}


def _match_out(conn: sqlite3.Connection, match: dict) -> dict:
    return {
        "id": match["id"],
        "round": match["round"],
        "match_index": match["match_index"],
        "status": match["status"],
        "player_a": _brief(conn, _side(match, "a")),
        "player_b": _brief(conn, _side(match, "b")),
        "player_a_score": match["player_a_score"],
        "player_b_score": match["player_b_score"],
        "winner_id": _winner(match),
        "table_id": match["table_id"],
        "prev_match_a_id": match["prev_match_a_id"],
        "prev_match_b_id": match["prev_match_b_id"],
        "bracket": match["bracket"],
        "placement_min": match["placement_min"],
        "placement_max": match["placement_max"],
        "result_type": match["result_type"],
        # A2 时间基础：必须显式透传，否则 KnockoutMatchOut 的默认 None 会静默丢掉时间。
        "called_at": match.get("called_at"),
        "started_at": match.get("started_at"),
        "finished_at": match.get("finished_at"),
    }


def _champion_path(main: list[dict], champion_id: int | None) -> list[int]:
    if champion_id is None:
        return []
    return [m["id"] for m in sorted(main, key=lambda m: m["round"]) if _winner(m) == champion_id]


def _placement_rows(conn: sqlite3.Connection, tournament: dict, matches: list[dict]) -> list[dict]:
    rows: list[dict] = []
    main = [m for m in matches if m["bracket"] == MatchBracket.MAIN.value]
    if not main:
        return rows
    final = max(main, key=lambda m: m["round"])
    if final["status"] == MatchStatus.FINISHED.value:
        rows.extend([
            {"rank": 1, "entry": _brief(conn, _winner(final)), "label": "冠军"},
            {"rank": 2, "entry": _brief(conn, _loser(final)), "label": "亚军"},
        ])
    placement_matches = [
        m for m in matches if m["bracket"] == MatchBracket.PLACEMENT.value
    ]
    bands = {
        (m["placement_min"], m["placement_max"])
        for m in placement_matches
        if m.get("placement_min") is not None and m.get("placement_max") is not None
    }
    for placement_min, placement_max in sorted(bands):
        band = [
            m for m in placement_matches
            if m.get("placement_min") == placement_min
            and m.get("placement_max") == placement_max
        ]
        final_match = max(band, key=lambda match: match["round"])
        if final_match["status"] != MatchStatus.FINISHED.value:
            continue
        labels = ("季军", "第四名") if placement_min == 3 else (
            f"第{placement_min}名", f"第{placement_min + 1}名"
        )
        rows.extend([
            {"rank": placement_min, "entry": _brief(conn, _winner(final_match)), "label": labels[0]},
            {"rank": placement_min + 1, "entry": _brief(conn, _loser(final_match)), "label": labels[1]},
        ])
    if tournament["bronze_mode"] == BronzeMode.JOINT_BRONZE.value and final["round"] >= 2:
        semis = [m for m in main if m["round"] == final["round"] - 1]
        if len(semis) == 2 and all(m["status"] == MatchStatus.FINISHED.value for m in semis):
            rows.extend(
                {"rank": 3, "entry": _brief(conn, _loser(semi)), "label": "并列季军"}
                for semi in semis
            )
    return sorted(rows, key=lambda row: row["rank"])


def get_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = _ensure_tournament(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
    main = [m for m in matches if m["bracket"] == MatchBracket.MAIN.value]
    if not main:
        return {"tournament": tournament, "rounds": [], "champion": None, "runner_up": None, "placements": [], "placement_matches": [], "champion_path_match_ids": []}

    max_round = max(m["round"] for m in main)
    rounds = []
    for round_no in range(1, max_round + 1):
        round_matches = sorted(
            [m for m in main if m["round"] == round_no], key=lambda m: m["match_index"] or 0
        )
        rounds.append({
            "round": round_no,
            "label": round_label(round_no, max_round),
            "matches": [_match_out(conn, m) for m in round_matches],
        })

    final = max(main, key=lambda m: m["round"])
    champion_id = _winner(final) if final["status"] == MatchStatus.FINISHED.value else None
    runner_id = _loser(final) if champion_id is not None else None
    placement_matches = sorted(
        [m for m in matches if m["bracket"] == MatchBracket.PLACEMENT.value],
        key=lambda m: (m["placement_min"] or 0, m["round"], m["match_index"] or 0),
    )
    return {
        "tournament": tournament,
        "rounds": rounds,
        "champion": _brief(conn, champion_id),
        "runner_up": _brief(conn, runner_id),
        "placement_matches": [
            {"range": [m["placement_min"], m["placement_max"]], "match": _match_out(conn, m)}
            for m in placement_matches
        ],
        "placements": _placement_rows(conn, tournament, matches),
        "champion_path_match_ids": _champion_path(main, champion_id),
    }
