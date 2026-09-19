"""团体队伍（TeamEntry）服务：复用 entries(entry_type='TEAM') + entry_members。

边界（读代码前请先读这段）：
- 队伍不是新表：一支队伍就是一个 Entry（entry_type='TEAM'），队员就是 entry_members。
  这样种子、分组、导出、级联删除等既有机制不用为团体赛再写一套。
- 队伍人数规则只有下限"至少 1 名队员"。具体赛制要求几人（几单几双、能否兼项）
  由赛制（domain/team_formats.py）决定，不臆造任何人数上限或"必须 3 人"之类规则。
- 队伍积分（entries.rating_points）默认 0：团体赛种子规则尚未冻结，
  这里不会用队员积分自动求和或推导种子，只接受调用方显式传入的值。
- 名单锁定分两层：
  1. **阶段锁**：进入 GROUP_STAGE 及以后禁止增删改队伍（与选手/名单服务一致）；
     `roster_confirmed` 只表示"名单已确认"，不作为编辑锁（系统没有"取消确认"能力）。
  2. **Runtime 锁（A4.1）**：队伍一旦有对抗进入 PLAYING/FINISHED，**队员名单冻结**——
     已开赛的对抗不能因为中途换人而让"已经不属于本队"的选手继续上场。
     改名与积分不受影响；对抗尚未开始时仍可修正名单，但已提交的 lineup 会在 start 时
     被原子重校验（见 services/team_runtime.py）。
  3. **与 Runtime 共用写锁**：改队员名单时先取 SQLite 写锁（`BEGIN IMMEDIATE`）再重新读取
     "对抗是否已开始"，与 `team_runtime._write_tx()` 是同一套协议；否则会出现
     "PATCH 读到 WAITING → start 抢先进入 PLAYING → PATCH 再替换成员"的竞态。
"""

import sqlite3
from contextlib import contextmanager

from .. import repository as repo
from ..models import EventType, TournamentStage

MIN_TEAM_MEMBERS = 1
MIN_TEAM_ENTRIES = 2

# entries.status 目前没有对应 Enum（既有代码直接用字符串），团体赛沿用同一口径：
# 已退赛（WITHDRAWN）的队伍不再计入"可以开赛"的队伍，也不能被安排新的对抗。
ENTRY_STATUS_ACTIVE = "ACTIVE"
ENTRY_STATUS_WITHDRAWN = "WITHDRAWN"


class TeamError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


@contextmanager
def _roster_write_tx(conn: sqlite3.Connection):
    """队员名单变更的写事务：语义与 `team_runtime._write_tx()` 一致。

    为什么需要它：`start_rubber()` 在写事务里重校验 lineup 并写入 PLAYING，而"改队员名单"
    同样是 read-check-write（先读对抗是否已开始，再替换成员）。如果这两者不上同一把锁，
    就可能出现"PATCH 读到 WAITING、start 抢先进入 PLAYING、PATCH 再替换成员"的竞态，
    最终留下"盘 PLAYING 但阵容里的选手已不属于该队"的坏状态。

    这里不把 `team_runtime._write_tx` 抽成公共模块，是因为 `team_runtime` 已经依赖 `teams`，
    反向 import 会形成循环依赖；两处实现刻意保持同样的语义（取锁 → 重新读状态 → 写 → 提交，
    异常回滚，锁等待超时返回可读的 409）。
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "within a transaction" in message:
            raise TeamError(f"内部错误：名单写事务嵌套（{exc}）", 500) from None
        raise TeamError("队伍名单正在被另一个请求处理，请稍后重试", 409) from None
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    try:
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        raise TeamError(f"队伍名单写入冲突，请稍后重试（{exc}）", 409) from None


def _tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TeamError("赛事不存在", 404)
    return tournament


def _team_tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """队伍相关操作的前置条件：赛事存在、是团体赛、仍在报名阶段。"""
    tournament = _tournament(conn, tournament_id)
    if tournament["event_type"] != EventType.TEAM.value:
        raise TeamError(
            f"当前赛事项目是 {tournament['event_type']}，只有团体赛（TEAM）可以管理队伍",
            409,
        )
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise TeamError("赛事已进入比赛阶段，队伍名单已锁定", 409)
    if tournament["roster_confirmed"]:
        raise TeamError("名单已确认并冻结，请先撤销冻结后再修改队伍", 409)
    return tournament


def _clean_name(display_name: str) -> str:
    name = display_name.strip() if isinstance(display_name, str) else ""
    if not name:
        raise TeamError("队伍名称不能为空", 422)
    return name


def _dedup_member_ids(member_ids: list[int]) -> list[int]:
    if not isinstance(member_ids, list) or any(
        not isinstance(pid, int) or isinstance(pid, bool) for pid in member_ids
    ):
        raise TeamError("队员必须是选手 id 列表", 422)
    if len(set(member_ids)) != len(member_ids):
        raise TeamError("同一支队伍里不能重复添加同一名选手", 422)
    if len(member_ids) < MIN_TEAM_MEMBERS:
        raise TeamError("队伍至少需要 1 名队员", 422)
    return list(member_ids)


def _check_members(
    conn: sqlite3.Connection,
    tournament_id: int,
    member_ids: list[int],
    exclude_entry_id: int | None = None,
) -> None:
    """队员必须属于本赛事，且不能已经挂在别的参赛实体上。

    entry_members 对 player_id 有全局 UNIQUE 约束，所以这里必须提前拦，
    否则会冒出 500（IntegrityError），而不是可读的业务错误。
    """
    roster = {p["id"]: p for p in repo.list_players(conn, tournament_id)}
    for player_id in member_ids:
        player = roster.get(player_id)
        if player is None:
            raise TeamError(f"选手 {player_id} 不存在或不属于本赛事", 404)
        holder = repo.find_entry_of_player(conn, tournament_id, player_id, exclude_entry_id)
        if holder is not None:
            raise TeamError(
                f"选手「{player['name']}」已在「{holder['display_name']}」中，不能同时代表两支队伍",
                409,
            )


def list_team_entries(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    _tournament(conn, tournament_id)
    return repo.list_entries_by_type(conn, tournament_id, EventType.TEAM.value)


def get_team_entry(conn: sqlite3.Connection, tournament_id: int, entry_id: int) -> dict:
    _tournament(conn, tournament_id)
    entry = repo.get_entry(conn, entry_id)
    if entry is None or entry["tournament_id"] != tournament_id:
        raise TeamError("队伍不存在", 404)
    if entry["entry_type"] != EventType.TEAM.value:
        raise TeamError(f"参赛实体 {entry_id} 不是团体队伍", 409)
    return entry


def create_team_entry(
    conn: sqlite3.Connection,
    tournament_id: int,
    display_name: str,
    member_ids: list[int],
    rating_points: int | None = None,
) -> dict:
    """新建一支队伍。rating_points 缺省 0（团体赛种子规则未冻结，不做积分推导）。"""
    _team_tournament(conn, tournament_id)
    name = _clean_name(display_name)
    members = _dedup_member_ids(member_ids)
    if rating_points is not None and (
        not isinstance(rating_points, int) or isinstance(rating_points, bool) or rating_points < 0
    ):
        raise TeamError("队伍积分必须是不小于 0 的整数", 422)
    if any(e["display_name"] == name for e in list_team_entries(conn, tournament_id)):
        raise TeamError(f"已存在同名队伍「{name}」", 409)
    _check_members(conn, tournament_id, members)

    entry = repo.create_entry(
        conn,
        tournament_id,
        EventType.TEAM.value,
        name,
        0 if rating_points is None else rating_points,
        members,
        seed_no=None,
    )
    conn.commit()
    return entry


def _apply_team_entry_update(
    conn: sqlite3.Connection,
    tournament_id: int,
    entry_id: int,
    display_name: str | None,
    member_ids: list[int] | None,
    rating_points: int | None,
) -> dict:
    """`update_team_entry` 的实际逻辑；**不 commit**，事务边界由调用方决定。

    所有会影响"名单是否冻结"的状态都在这里（即调用方的事务内）重新读取，
    保证"读到的状态"与"写入"之间不会插入其它写事务。
    """
    _team_tournament(conn, tournament_id)
    entry = get_team_entry(conn, tournament_id, entry_id)

    name = entry["display_name"] if display_name is None else _clean_name(display_name)
    if rating_points is not None and (
        not isinstance(rating_points, int) or isinstance(rating_points, bool) or rating_points < 0
    ):
        raise TeamError("队伍积分必须是不小于 0 的整数", 422)
    points = entry["rating_points"] if rating_points is None else rating_points

    if name != entry["display_name"] and any(
        e["display_name"] == name for e in list_team_entries(conn, tournament_id)
    ):
        raise TeamError(f"已存在同名队伍「{name}」", 409)

    if member_ids is not None:
        # Runtime 锁：队伍已有对抗进入 PLAYING/FINISHED 时不允许再动队员名单，
        # 否则已经提交/正在进行的 lineup 可能指向"已经不属于该队"的选手。
        # 这个判断必须在 `_roster_write_tx` 的写锁之内执行（见 update_team_entry）。
        started_tie = repo.find_started_tie_for_entry(conn, entry_id)
        if started_tie is not None:
            raise TeamError(
                f"该队伍已进入比赛（对抗 #{started_tie['id']}，状态 {started_tie['status']}），"
                f"队员名单已锁定：团体赛名单在对抗开始后不可更改",
                409,
            )
        members = _dedup_member_ids(member_ids)
        _check_members(conn, tournament_id, members, exclude_entry_id=entry_id)
        repo.replace_entry_members(conn, entry_id, members)

    if name != entry["display_name"] or points != entry["rating_points"]:
        repo.update_entry(conn, entry_id, name, points)

    return get_team_entry(conn, tournament_id, entry_id)


def update_team_entry(
    conn: sqlite3.Connection,
    tournament_id: int,
    entry_id: int,
    display_name: str | None = None,
    member_ids: list[int] | None = None,
    rating_points: int | None = None,
) -> dict:
    """改名 / 换队员 / 改积分；只传需要改的字段。

    member_ids 是全量替换（不是追加），并会先校验再落库。

    事务边界：
    - **只改队名 / 积分**：走普通路径（读 → 写 → commit），它们破坏不了 lineup 不变量；
    - **改队员名单**：与 Runtime 的 `start_rubber()` 共用同一把 SQLite 写锁——
      先 `BEGIN IMMEDIATE` 拿到写锁，再在事务内重新读取"对抗是否已开始"，然后替换成员并提交。
      这样两个方向都只会是合法结果之一：
        * PATCH 先取锁 → 成员替换提交；随后 start 重新校验 lineup 时会发现队员已离队 → 409；
        * start 先取锁 → 盘进入 PLAYING；随后 PATCH 会读到对抗已开始 → 409（名单锁定）。
    """
    if member_ids is not None:
        with _roster_write_tx(conn):
            return _apply_team_entry_update(
                conn, tournament_id, entry_id, display_name, member_ids, rating_points
            )
    result = _apply_team_entry_update(
        conn, tournament_id, entry_id, display_name, None, rating_points
    )
    conn.commit()
    return result


def delete_team_entry(conn: sqlite3.Connection, tournament_id: int, entry_id: int) -> None:
    """删除队伍。已被团体对抗引用的队伍禁止删除（否则会留下悬空引用）。"""
    _team_tournament(conn, tournament_id)
    get_team_entry(conn, tournament_id, entry_id)
    tie = repo.find_tie_referencing_entry(conn, entry_id)
    if tie is not None:
        raise TeamError(f"该队伍已出现在团体对抗 #{tie['id']} 中，不能删除", 409)
    repo.delete_entry(conn, entry_id)
    conn.commit()


def validate_team_roster(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """确认团体赛名单前的整体校验（由 entries.confirm_roster 调用）。

    只要求自洽：至少 2 支"在赛队伍"、每支在赛队伍至少 1 人、没有选手被落下或重复代表两队。
    不校验队伍人数是否满足某个赛制——赛制尚未冻结。

    与退赛（整项退赛，见 services/entries.py::withdraw_from_tournament）的交互：
    - 已退赛的队伍**不计入**"至少 2 支队伍"——退赛队伍不会再上场，不能用来凑数；
    - 但已退赛队伍里的选手仍算"有队"，不强迫组织者删除历史名单。
    """
    entries = list_team_entries(conn, tournament_id)
    players = repo.list_players(conn, tournament_id)
    active = [entry for entry in entries if entry["status"] == ENTRY_STATUS_ACTIVE]
    if len(active) < MIN_TEAM_ENTRIES:
        raise TeamError(
            f"团体赛至少需要 {MIN_TEAM_ENTRIES} 支在赛队伍才能确认名单"
            f"（已退赛队伍不计入，当前 {len(active)} 支）",
            409,
        )
    member_ids: list[int] = []
    for entry in entries:
        if entry["status"] == ENTRY_STATUS_ACTIVE and len(entry["members"]) < MIN_TEAM_MEMBERS:
            raise TeamError(f"队伍「{entry['display_name']}」还没有队员", 409)
        member_ids.extend(m["player_id"] for m in entry["members"])
    # 兜底：entry_members 对 player_id 有 UNIQUE 约束，正常情况下不会重复，
    # 这里只是把"万一重复"变成可读错误而不是坏数据。
    if len(set(member_ids)) != len(member_ids):
        raise TeamError("有选手同时出现在两支队伍中，请先修正队伍名单", 409)
    assigned = set(member_ids)
    missing = [p["id"] for p in players if p["id"] not in assigned]
    if missing:
        raise TeamError(
            f"仍有 {len(missing)} 名选手没有加入任何队伍，不能确认名单", 409
        )
    return entries
