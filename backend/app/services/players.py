"""选手服务：增删改前的业务规则校验。

规则：
- 赛事不存在 → 404；
- 赛事进入比赛阶段（GROUP_STAGE 及以后）后，选手名单锁定，禁止增删改；
- 已分组的选手禁止删除（需先清空分组）。
"""

import sqlite3

from .. import repository as repo
from ..models import EventType, TournamentStage
from . import teams as teams_service


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
    if tournament["event_type"] == EventType.TEAM.value and tournament["roster_confirmed"]:
        raise PlayerError("团体赛名单已确认并冻结，请先撤销冻结后再修改选手", 409)


def delete_player(conn: sqlite3.Connection, tournament_id: int, player_id: int) -> None:
    with teams_service._roster_write_tx(conn):
        ensure_players_editable(conn, tournament_id)
        player = repo.get_player(conn, player_id)
        if player is None:
            raise PlayerError("选手不存在", 404)
        if player["group_id"] is not None:
            raise PlayerError("选手已分组，请先解除分组后再删除", 409)
        repo.delete_player(conn, player_id)


def _sync_singles_entry_seeds(
    conn: sqlite3.Connection, tournament_id: int, ranked_player_ids: list[int]
) -> None:
    """把选手种子镜像到单打 Entry，保证"选手种子"与"Entry 种子"只有一个真实来源。

    分组分散与淘汰赛徽标读的是 entries.seed_no，而编辑入口写的是 players.seed_no；
    这里在每次修改种子后同步一次，避免"UI 改了种子但分组仍按旧种子"。
    只认 entry_type == SINGLES：双打 Entry（两名成员）与团体 Entry（成员数不定，
    可以是 1 人也可以是 4 人）的种子规则都尚未冻结，这里不触碰。
    """
    singles = [
        entry for entry in repo.list_entries(conn, tournament_id)
        if entry["entry_type"] == EventType.SINGLES.value
    ]
    if not singles:
        return
    entry_of = {entry["members"][0]["player_id"]: entry["id"] for entry in singles}
    for entry in singles:
        repo.set_entry_seed(conn, entry["id"], None)
    for seed_no, player_id in enumerate(ranked_player_ids, start=1):
        entry_id = entry_of.get(player_id)
        if entry_id is not None:
            repo.set_entry_seed(conn, entry_id, seed_no)


def set_seeds(
    conn: sqlite3.Connection, tournament_id: int, player_ids: list[int]
) -> list[dict]:
    """按给定顺序设置种子（1号、2号…N号），其余选手清空种子。返回更新后的选手列表。"""
    with teams_service._roster_write_tx(conn):
        return _set_seeds_unlocked(conn, tournament_id, player_ids)


def _set_seeds_unlocked(
    conn: sqlite3.Connection, tournament_id: int, player_ids: list[int]
) -> list[dict]:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PlayerError("赛事不存在", 404)
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise PlayerError("赛事已进入比赛阶段，种子设置已锁定", 409)
    if tournament["event_type"] == EventType.TEAM.value and tournament["roster_confirmed"]:
        raise PlayerError("团体赛名单已确认并冻结，请先撤销冻结后再设置种子", 409)

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
    _sync_singles_entry_seeds(conn, tournament_id, player_ids)
    return repo.list_players(conn, tournament_id)


def auto_seed_by_rating(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """按赛事积分自动设置种子（单打）：积分高者 S1…SN。

    排序稳定：rating_points 降序，同分按选手 id 升序（不使用随机）。
    默认取前 group_count 名（不超过参赛人数）；只是在用户点击时执行一次，
    不会在分组时偷偷覆盖手工种子，生成后仍可手工调整。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PlayerError("赛事不存在", 404)
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise PlayerError("赛事已进入比赛阶段，种子设置已锁定", 409)
    if tournament["event_type"] != EventType.SINGLES.value:
        raise PlayerError(
            "当前仅支持单打按积分自动生成种子；双打与团体赛的种子规则尚未冻结", 409
        )
    players = repo.list_players(conn, tournament_id)
    if not players:
        raise PlayerError("请先添加或导入选手", 409)

    limit = min(tournament["group_count"], len(players))
    ranked = sorted(players, key=lambda p: (-p["rating_points"], p["id"]))[:limit]
    return set_seeds(conn, tournament_id, [p["id"] for p in ranked])


DEMO_COLLEGES = ["计算机学院", "自动化学院", "机械学院", "电子信息学院"]


def generate_demo_players(
    conn: sqlite3.Connection, tournament_id: int, count: int, with_seeds: bool
) -> list[dict]:
    """Demo：追加生成 count 名演示选手（选手N..），可选把前 4 名设为种子。

    仅 REGISTRATION 阶段可用；追加在现有选手之后，不清空已有选手。
    """
    with teams_service._roster_write_tx(conn):
        return _generate_demo_players_unlocked(conn, tournament_id, count, with_seeds)


def _generate_demo_players_unlocked(
    conn: sqlite3.Connection, tournament_id: int, count: int, with_seeds: bool
) -> list[dict]:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PlayerError("赛事不存在", 404)
    ensure_players_editable(conn, tournament_id)
    if not (1 <= count <= 24):
        raise PlayerError("生成数量需在 1~24 之间", 422)

    existing = repo.list_players(conn, tournament_id)
    if len(existing) + count > 120:
        raise PlayerError(f"生成后将超过 120 人上限，当前已有 {len(existing)} 人", 409)
    start = len(existing) + 1
    added: list[dict] = []
    for i in range(start, start + count):
        name = f"选手{i:02d}"
        college = DEMO_COLLEGES[(i - 1) % len(DEMO_COLLEGES)]
        # 让双打“相近积分随机配对”在演示数据中能直接看出效果。
        rating_points = 1500 - ((i - 1) % 12) * 35
        added.append(repo.add_player(conn, tournament_id, name, college, rating_points))

    if with_seeds and count > 0:
        seed_count = min(4, tournament["group_count"], count)
        seeded = added[:seed_count]
        repo.clear_tournament_seeds(conn, tournament_id)
        for i, p in enumerate(seeded):
            repo.set_player_seed(conn, p["id"], i + 1)
        # 名单已确认时，Entry 种子必须跟着选手种子走（复用同一套同步逻辑，不新增实现）。
        _sync_singles_entry_seeds(conn, tournament_id, [p["id"] for p in seeded])

    return repo.list_players(conn, tournament_id)
