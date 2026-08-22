"""选手服务：增删改前的业务规则校验。

规则：
- 赛事不存在 → 404；
- 赛事进入比赛阶段（GROUP_STAGE 及以后）后，选手名单锁定，禁止增删改；
- 已分组的选手禁止删除（需先清空分组）。
"""

import sqlite3

from .. import repository as repo
from ..models import TournamentStage


class PlayerError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def ensure_players_editable(conn: sqlite3.Connection, tournament_id: int) -> None:
    """比赛阶段锁定：仅 REGISTRATION 阶段允许增删改选手。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PlayerError("赛事不存在", 404)
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise PlayerError("赛事已进入比赛阶段，选手名单已锁定", 409)


def delete_player(conn: sqlite3.Connection, tournament_id: int, player_id: int) -> None:
    ensure_players_editable(conn, tournament_id)
    player = repo.get_player(conn, player_id)
    if player is None:
        raise PlayerError("选手不存在", 404)
    if player["group_id"] is not None:
        raise PlayerError("选手已分组，请先解除分组后再删除", 409)
    repo.delete_player(conn, player_id)
    conn.commit()
