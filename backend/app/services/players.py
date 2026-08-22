"""选手服务：删除选手前的业务规则校验。"""

import sqlite3

from .. import repository as repo


class PlayerDeleteError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def delete_player(conn: sqlite3.Connection, player_id: int) -> None:
    player = repo.get_player(conn, player_id)
    if player is None:
        raise PlayerDeleteError("选手不存在", 404)
    if player["group_id"] is not None:
        raise PlayerDeleteError("选手已分组，请先解除分组后再删除", 409)
    repo.delete_player(conn, player_id)
    conn.commit()
