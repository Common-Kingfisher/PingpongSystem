"""比分录入与修改服务。

设计要点：
- 排名/统计从不存储增量，而是读取时由全部 FINISHED 比赛整体重算，
  因此修改比分天然"撤销旧结果、生效新结果"，不存在累计污染；
- 录入：PLAYING → FINISHED（释放球台）；
- 修改：仅允许对 FINISHED 比赛，更新比分与胜者，不改变状态与球台；
- 淘汰赛：录分后胜者自动晋级下一轮；改分后整条下游链级联重置再重新晋级。
"""

import hashlib
import json
import sqlite3

from .. import repository as repo
from ..models import MatchStage, MatchStatus, ResultType, TableStatus
from . import knockout as knockout_service


class ScoreError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _validate_scores(score_a: int, score_b: int, games_to_win: int) -> None:
    if score_a < 0 or score_b < 0:
        raise ScoreError("比分不能为负数", 422)
    if score_a == score_b:
        raise ScoreError("比赛不允许平局")
    if max(score_a, score_b) != games_to_win:
        raise ScoreError(f"大比分胜局数必须为 {games_to_win}", 422)


def _winner_id(
    player_a_id: int, player_b_id: int, score_a: int, score_b: int
) -> int:
    """比分高者胜；返回胜者选手 id（不是比分值）。"""
    return player_a_id if score_a > score_b else player_b_id


def _validate_game(a: int, b: int, points_to_win: int, index: int) -> None:
    """校验单局比分是否符合 points_to_win 分制。

    - 未进入平分延长（loser < points_to_win - 1）：胜方必须恰好得到 points_to_win 分；
    - 进入平分延长（loser >= points_to_win - 1）：胜方必须恰好领先 2 分。
    """
    if a < 0 or b < 0:
        raise ScoreError(f"第 {index} 局比分不能为负数", 422)
    if a == b:
        raise ScoreError(f"第 {index} 局不允许平局", 422)
    winner = max(a, b)
    loser = min(a, b)
    if loser < points_to_win - 1:
        if winner != points_to_win:
            raise ScoreError(
                f"第 {index} 局未进入平分延长，胜方必须恰好得到 {points_to_win} 分", 422
            )
    elif winner != loser + 2:
        raise ScoreError(f"第 {index} 局进入平分延长后，胜方必须恰好领先 2 分", 422)


def _validate_games(games: list[tuple[int, int]], games_to_win: int, points_to_win: int) -> tuple[int, int]:
    if not games:
        raise ScoreError("请至少录入一局比分", 422)
    wins_a = wins_b = 0
    for index, (a, b) in enumerate(games, start=1):
        _validate_game(a, b, points_to_win, index)
        if a > b:
            wins_a += 1
        else:
            wins_b += 1
        if max(wins_a, wins_b) >= games_to_win and index != len(games):
            raise ScoreError("比赛已经分出胜负，请删除多余局分", 422)
    if max(wins_a, wins_b) != games_to_win:
        raise ScoreError(f"比赛尚未达到 {games_to_win} 局胜利", 422)
    return wins_a, wins_b


def _side_ids(match: dict) -> tuple[int | None, int | None]:
    return (
        match.get("entry_a_id") or match.get("player_a_id"),
        match.get("entry_b_id") or match.get("player_b_id"),
    )


def _ensure_match(conn: sqlite3.Connection, match_id: int) -> dict:
    match = repo.get_match(conn, match_id)
    if match is None:
        raise ScoreError("比赛不存在", 404)
    return match


def _claim_request(
    conn: sqlite3.Connection,
    request_id: str | None,
    match_id: int,
    action: str,
    score_a: int | None,
    score_b: int | None,
    games: list[tuple[int, int]] | None,
    result_type: str,
    forfeit_entry_id: int | None,
    note: str | None,
    operator_name: str | None,
    change_reason: str | None,
) -> bool:
    """返回 True 表示同一请求已成功处理，可直接返回当前比赛。"""
    if request_id is None:
        return False
    raw = json.dumps(
        [score_a, score_b, games, result_type, forfeit_entry_id, note, operator_name, change_reason],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    state = repo.claim_score_request(conn, request_id, match_id, action, fingerprint)
    if state == "CONFLICT":
        raise ScoreError("请求编号已用于其他比分操作，请刷新后重试", 409)
    return state == "REPLAY"


def _snapshot(conn: sqlite3.Connection, match_id: int) -> dict:
    """审计快照只保存比分相关事实，避免日后展示时被当前数据污染。"""
    match = repo.decorate_match(conn, _ensure_match(conn, match_id))
    return {
        "status": match.get("status"),
        "table_id": match.get("table_id"),
        "player_a_score": match.get("player_a_score"),
        "player_b_score": match.get("player_b_score"),
        "winner_id": match.get("winner_id"),
        "winner_entry_id": match.get("winner_entry_id"),
        "result_type": match.get("result_type"),
        "forfeit_entry_id": match.get("forfeit_entry_id"),
        "result_note": match.get("result_note"),
        "games": [
            {
                "game_no": game["game_no"],
                "side_a_score": game["side_a_score"],
                "side_b_score": game["side_b_score"],
                "winner_entry_id": game.get("winner_entry_id"),
            }
            for game in match["games"]
        ],
    }


def _audit(
    conn: sqlite3.Connection,
    match_id: int,
    action: str,
    before: dict,
    operator_name: str | None,
    change_reason: str | None,
    request_id: str | None,
) -> None:
    repo.create_score_audit(
        conn,
        match_id,
        action,
        json.dumps(before, ensure_ascii=False, separators=(",", ":")),
        json.dumps(_snapshot(conn, match_id), ensure_ascii=False, separators=(",", ":")),
        operator_name.strip() if operator_name else None,
        change_reason.strip() if change_reason else None,
        request_id,
    )


def _require_revision_audit(operator_name: str | None, change_reason: str | None) -> None:
    if not operator_name or not operator_name.strip():
        raise ScoreError("修改比分必须填写操作人", 422)
    if not change_reason or len(change_reason.strip()) < 2:
        raise ScoreError("修改比分必须填写至少 2 个字的修改理由", 422)


def record_score(
    conn: sqlite3.Connection,
    match_id: int,
    score_a: int | None,
    score_b: int | None,
    games: list[tuple[int, int]] | None = None,
    result_type: str = ResultType.NORMAL.value,
    forfeit_entry_id: int | None = None,
    note: str | None = None,
    request_id: str | None = None,
    operator_name: str | None = None,
    change_reason: str | None = None,
) -> dict:
    """录入比分：允许 PLAYING 或 WAITING 比赛 → FINISHED。

    为了支持在淘汰赛页直接录入比分（无需先分配球台），WAITING 且双方就绪的
    比赛也可直接出结果；若已分配球台（PLAYING）则释放球台。
    """
    match = _ensure_match(conn, match_id)
    before = _snapshot(conn, match_id)
    if _claim_request(
        conn, request_id, match_id, "RECORD", score_a, score_b, games,
        result_type, forfeit_entry_id, note, operator_name, change_reason,
    ):
        return repo.decorate_match(conn, match)
    if match["status"] not in (MatchStatus.PLAYING.value, MatchStatus.WAITING.value):
        raise ScoreError("只有进行中或待安排的比赛可以录入比分")
    side_a, side_b = _side_ids(match)
    if side_a is None or side_b is None:
        raise ScoreError("比赛双方尚未就绪")
    tournament = repo.get_tournament(conn, match["tournament_id"])

    if result_type == ResultType.NORMAL.value:
        # 首次录分只接受大比分；逐局小分仅作为已结束小组赛的补录，走 revise_score。
        if games is not None:
            raise ScoreError("首次录分只支持大比分，不支持逐局比分", 422)
        if score_a is None or score_b is None:
            raise ScoreError("请录入完整比分", 422)
        _validate_scores(score_a, score_b, tournament["games_to_win"])
        winner_side = side_a if score_a > score_b else side_b
        repo.replace_match_games(conn, match_id, [], match.get("entry_a_id"), match.get("entry_b_id"))
    else:
        if forfeit_entry_id not in (side_a, side_b):
            raise ScoreError("请选择弃权或未到场的一方", 422)
        winner_side = side_b if forfeit_entry_id == side_a else side_a
        # 小组赛按弃权负处理：胜方取得本场胜利及应胜局数，弃权方赛事积分为 0；
        # 淘汰赛只表达直接晋级，不伪造逐局比分。
        if match["stage"] == MatchStage.GROUP.value:
            score_a = tournament["games_to_win"] if winner_side == side_a else 0
            score_b = tournament["games_to_win"] if winner_side == side_b else 0
        else:
            score_a = score_b = 0
        repo.replace_match_games(conn, match_id, [], match.get("entry_a_id"), match.get("entry_b_id"))
    winner_entry = winner_side if match.get("entry_a_id") is not None else None
    winner_player = winner_side if match.get("entry_a_id") is None else (
        match.get("player_a_id") if winner_side == side_a else match.get("player_b_id")
    )

    # WAITING 直接录分（例如淘汰赛页面不先排台）：started_at 保持为空，只写 finished_at，
    # 这类比赛不进入真实耗时样本；PLAYING 录分则保留已有的 called_at / started_at。
    repo.mark_match_finished(
        conn,
        match_id,
        player_a_score=score_a,
        player_b_score=score_b,
        winner_id=winner_player,
        winner_entry_id=winner_entry,
        result_type=result_type,
        forfeit_entry_id=forfeit_entry_id,
        result_note=note,
    )
    if match["table_id"] is not None:
        repo.update_table_status(conn, match["table_id"], TableStatus.FREE.value)
    # 淘汰赛：胜者晋级下一轮；决赛结束 → 赛事 FINISHED
    if match["stage"] == MatchStage.KNOCKOUT.value:
        knockout_service.advance_winner(conn, repo.get_match(conn, match_id))
        knockout_service.sync_stage(conn, match["tournament_id"])
    elif match["group_id"] is not None:
        repo.invalidate_qualification_decision(conn, match["group_id"], "相关比赛结果已录入")
    _audit(conn, match_id, "RECORD", before, operator_name, change_reason, request_id)
    conn.commit()
    return repo.decorate_match(conn, repo.get_match(conn, match_id))


def revise_score(
    conn: sqlite3.Connection,
    match_id: int,
    score_a: int | None,
    score_b: int | None,
    games: list[tuple[int, int]] | None = None,
    result_type: str = ResultType.NORMAL.value,
    forfeit_entry_id: int | None = None,
    note: str | None = None,
    request_id: str | None = None,
    operator_name: str | None = None,
    change_reason: str | None = None,
    require_audit: bool = False,
) -> dict:
    """修改已结束比赛的比分（纠错）。

    淘汰赛限制：如果任一胜者线或负者排位线的下游比赛已经 PLAYING/FINISHED，
    则阻止修改；全部下游尚未开始时允许修改并重新同步双方签位。
    """
    match = _ensure_match(conn, match_id)
    before = _snapshot(conn, match_id)
    if _claim_request(
        conn, request_id, match_id, "REVISE", score_a, score_b, games,
        result_type, forfeit_entry_id, note, operator_name, change_reason,
    ):
        return repo.decorate_match(conn, match)
    if match["status"] != MatchStatus.FINISHED.value:
        raise ScoreError("只有已结束的比赛可以修改比分")
    side_a, side_b = _side_ids(match)
    tournament = repo.get_tournament(conn, match["tournament_id"])

    if match["stage"] == MatchStage.GROUP.value and repo.list_matches(
        conn, match["tournament_id"], MatchStage.KNOCKOUT.value
    ):
        raise ScoreError("淘汰赛签表已经生成，当前版本不支持直接修改小组赛结果；请在生成签表前完成更正，或联系管理员处理。")

    # 补录/更新逐局小分：仅 FINISHED GROUP；大比分、winner、status 一律不变。
    if result_type == ResultType.NORMAL.value and games is not None:
        if match["stage"] != MatchStage.GROUP.value:
            raise ScoreError("只有小组赛支持补录逐局小分", 422)
        stored_a, stored_b = match["player_a_score"], match["player_b_score"]
        if stored_a is None or stored_b is None:
            raise ScoreError("该比赛尚未确认大比分", 409)
        derived_a, derived_b = _validate_games(
            games, tournament["games_to_win"], tournament["points_to_win"]
        )
        if (derived_a, derived_b) != (stored_a, stored_b):
            raise ScoreError("逐局小比分与大比分不一致", 422)
        if require_audit:
            _require_revision_audit(operator_name, change_reason)
        repo.replace_match_games(
            conn, match_id, games,
            match.get("entry_a_id"), match.get("entry_b_id"),
        )
        # 校验全部通过后才更新备注：note is None 保留原备注，note == "" 显式清空。
        if note is not None:
            repo.update_match(conn, match_id, result_note=note)
        if match["group_id"] is not None:
            repo.invalidate_qualification_decision(conn, match["group_id"], "相关比赛小比分已修改")
        _audit(conn, match_id, "REVISE", before, operator_name, change_reason, request_id)
        conn.commit()
        return repo.decorate_match(conn, repo.get_match(conn, match_id))

    # 修改大比分（或异常结果）：KNOCKOUT 需先检查下游是否已开始。
    if match["stage"] == MatchStage.KNOCKOUT.value:
        for descendant in knockout_service.descendants(conn, match_id):
            if descendant["status"] in (
                MatchStatus.PLAYING.value,
                MatchStatus.FINISHED.value,
            ):
                raise ScoreError("该结果已经影响后续比赛。请先处理后续比赛后再修改本场结果。")

    if result_type == ResultType.NORMAL.value:
        if score_a is None or score_b is None:
            raise ScoreError("请录入完整比分", 422)
        _validate_scores(score_a, score_b, tournament["games_to_win"])
        winner_side = side_a if score_a > score_b else side_b
        if require_audit:
            _require_revision_audit(operator_name, change_reason)
        # 修改大比分后，旧逐局数据不再可信，予以清除。
        repo.replace_match_games(conn, match_id, [], match.get("entry_a_id"), match.get("entry_b_id"))
    else:
        if forfeit_entry_id not in (side_a, side_b):
            raise ScoreError("请选择弃权或未到场的一方", 422)
        if require_audit:
            _require_revision_audit(operator_name, change_reason)
        winner_side = side_b if forfeit_entry_id == side_a else side_a
        if match["stage"] == MatchStage.GROUP.value:
            score_a = tournament["games_to_win"] if winner_side == side_a else 0
            score_b = tournament["games_to_win"] if winner_side == side_b else 0
        else:
            score_a = score_b = 0
        repo.replace_match_games(conn, match_id, [], match.get("entry_a_id"), match.get("entry_b_id"))

    winner_entry = winner_side if match.get("entry_a_id") is not None else None
    winner_player = winner_side if match.get("entry_a_id") is None else (
        match.get("player_a_id") if winner_side == side_a else match.get("player_b_id")
    )

    update_fields = {
        "player_a_score": score_a,
        "player_b_score": score_b,
        "winner_id": winner_player,
        "winner_entry_id": winner_entry,
        "result_type": result_type,
        "forfeit_entry_id": forfeit_entry_id,
    }
    # 与小分补录路径统一：省略 note 时保留原备注；显式空串才清空。
    if note is not None:
        update_fields["result_note"] = note
    # 纠错不得改动 called_at / started_at / finished_at：时间字段不在 _MATCH_UPDATEABLE 中，
    # 因此这里天然只改比分与结果，finished_at 保持比赛实际结束的时刻。
    repo.update_match(conn, match_id, **update_fields)

    if match["stage"] == MatchStage.KNOCKOUT.value:
        # 改分：下游链重置（撤销旧晋级槽位），再按新结果重新晋级
        knockout_service.reset_branch(conn, match_id)
        knockout_service.advance_winner(conn, repo.get_match(conn, match_id))
        knockout_service.sync_stage(conn, match["tournament_id"])
    elif match["group_id"] is not None:
        repo.invalidate_qualification_decision(conn, match["group_id"], "相关比赛结果已修改")
    _audit(conn, match_id, "REVISE", before, operator_name, change_reason, request_id)
    conn.commit()
    return repo.decorate_match(conn, repo.get_match(conn, match_id))
