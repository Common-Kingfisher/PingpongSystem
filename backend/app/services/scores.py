"""比分录入与修改服务。

设计要点：
- 排名/统计从不存储增量，而是读取时由全部 FINISHED 比赛整体重算，
  因此修改比分天然"撤销旧结果、生效新结果"，不存在累计污染；
- 录入：PLAYING → FINISHED（释放球台）；
- 修改：仅允许对 FINISHED 比赛，更新比分与胜者，不改变状态与球台。
"""

import sqlite3

from .. import repository as repo
from ..models import MatchStatus, TableStatus


class ScoreError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _validate_scores(score_a: int, score_b: int) -> None:
    if score_a < 0 or score_b < 0:
        raise ScoreError("比分不能为负数", 422)
    if score_a == score_b:
        raise ScoreError("比赛不允许平局")


def _winner_id(
    player_a_id: int, player_b_id: int, score_a: int, score_b: int
) -> int:
    """比分高者胜；返回胜者选手 id（不是比分值）。"""
    return player_a_id if score_a > score_b else player_b_id


def _ensure_match(conn: sqlite3.Connection, match_id: int) -> dict:
    match = repo.get_match(conn, match_id)
    if match is None:
        raise ScoreError("比赛不存在", 404)
    return match


def record_score(
    conn: sqlite3.Connection, match_id: int, score_a: int, score_b: int
) -> dict:
    """录入比分：PLAYING 比赛 → FINISHED，释放球台。"""
    match = _ensure_match(conn, match_id)
    if match["status"] != MatchStatus.PLAYING.value:
        raise ScoreError("只有进行中的比赛可以录入比分")
    _validate_scores(score_a, score_b)
    winner = _winner_id(match["player_a_id"], match["player_b_id"], score_a, score_b)

    repo.update_match(
        conn,
        match_id,
        status=MatchStatus.FINISHED.value,
        player_a_score=score_a,
        player_b_score=score_b,
        winner_id=winner,
    )
    if match["table_id"] is not None:
        repo.update_table_status(conn, match["table_id"], TableStatus.FREE.value)
    conn.commit()
    return repo.get_match(conn, match_id)


def revise_score(
    conn: sqlite3.Connection, match_id: int, score_a: int, score_b: int
) -> dict:
    """修改已结束比赛的比分（纠错）。"""
    match = _ensure_match(conn, match_id)
    if match["status"] != MatchStatus.FINISHED.value:
        raise ScoreError("只有已结束的比赛可以修改比分")
    _validate_scores(score_a, score_b)
    winner = _winner_id(match["player_a_id"], match["player_b_id"], score_a, score_b)

    repo.update_match(
        conn,
        match_id,
        player_a_score=score_a,
        player_b_score=score_b,
        winner_id=winner,
    )
    conn.commit()
    return repo.get_match(conn, match_id)
