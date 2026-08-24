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


def set_seeds(
    conn: sqlite3.Connection, tournament_id: int, player_ids: list[int]
) -> list[dict]:
    """按给定顺序设置种子（1号、2号…N号），其余选手清空种子。返回更新后的选手列表。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PlayerError("赛事不存在", 404)
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise PlayerError("赛事已进入比赛阶段，种子设置已锁定", 409)

    if len(set(player_ids)) != len(player_ids):
        raise PlayerError("种子选手不能重复", 409)
    if len(player_ids) > tournament["group_count"]:
        raise PlayerError(
            f"当前赛事有 {tournament['group_count']} 个小组，最多可设置 {tournament['group_count']} 名种子选手",
            409,
        )

    players = repo.list_players(conn, tournament_id)
    ids = {p["id"] for p in players}
    for pid in player_ids:
        if pid not in ids:
            raise PlayerError("选手不存在或不属于该赛事", 404)

    repo.clear_tournament_seeds(conn, tournament_id)
    for i, pid in enumerate(player_ids):
        repo.set_player_seed(conn, pid, i + 1)
    conn.commit()
    return repo.list_players(conn, tournament_id)


DEMO_COLLEGES = ["计算机学院", "自动化学院", "机械学院", "电子信息学院"]


def generate_demo_players(
    conn: sqlite3.Connection, tournament_id: int, count: int, with_seeds: bool
) -> list[dict]:
    """Demo：追加生成 count 名演示选手（选手N..），可选把前 4 名设为种子。

    仅 REGISTRATION 阶段可用；追加在现有选手之后，不清空已有选手。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PlayerError("赛事不存在", 404)
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise PlayerError("赛事已进入比赛阶段，选手名单已锁定", 409)
    if not (1 <= count <= 24):
        raise PlayerError("生成数量需在 1~24 之间", 422)

    existing = repo.list_players(conn, tournament_id)
    start = len(existing) + 1
    added: list[dict] = []
    for i in range(start, start + count):
        name = f"选手{i:02d}"
        college = DEMO_COLLEGES[(i - 1) % len(DEMO_COLLEGES)]
        added.append(repo.add_player(conn, tournament_id, name, college))

    if with_seeds and count > 0:
        seed_count = min(4, tournament["group_count"], count)
        repo.clear_tournament_seeds(conn, tournament_id)
        for i, p in enumerate(added[:seed_count]):
            repo.set_player_seed(conn, p["id"], i + 1)

    conn.commit()
    return repo.list_players(conn, tournament_id)
