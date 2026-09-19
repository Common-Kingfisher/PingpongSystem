"""团体赛 Excel 式名单工作表的原子读写服务。"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from .. import repository as repo
from ..models import EventType, TournamentStage
from . import players, teams


def _error(message: str, code: int = 409) -> teams.TeamError:
    return teams.TeamError(message, code)


def _sheet(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise _error("赛事不存在", 404)
    if tournament["event_type"] != EventType.TEAM.value:
        raise _error("只有团体赛（TEAM）可以使用队伍名单工作表", 409)
    team_rows = repo.list_entries_by_type(conn, tournament_id, EventType.TEAM.value)
    players = repo.list_players(conn, tournament_id)
    payload = {
        "tournament": tournament,
        "teams": team_rows,
        "players": players,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["revision"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return payload


def get_sheet(conn: sqlite3.Connection, tournament_id: int) -> dict:
    return _sheet(conn, tournament_id)


def _require_editable(tournament: dict) -> None:
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise _error("赛事已进入比赛阶段，队伍名单已锁定")
    if tournament["roster_confirmed"]:
        raise _error("名单已确认并冻结，请先撤销冻结后再修改")


def _unique(values: list[object], label: str) -> None:
    if len(values) != len(set(values)):
        raise _error(f"{label}不能重复", 422)


def _protect_started_team_members(
    conn: sqlite3.Connection,
    current: dict,
    draft_teams: list[dict],
    members: dict[str, list[dict]],
) -> None:
    """已开赛队伍的成员和队内顺序不能被工作表批量写绕过。

    常规队伍编辑接口在更新成员前已有同样的保护。工作表会先清空再重建
    entry_members 以支持跨队调换，因此必须在清空前比较完整的成员快照。
    """
    current_by_id = {team["id"]: team for team in current["teams"]}
    for team in draft_teams:
        team_id = team["id"]
        if team_id is None:
            continue
        before = [member["player_id"] for member in current_by_id[team_id]["members"]]
        after = [
            player["id"]
            for player in sorted(members[team["key"]], key=lambda item: item["member_order"])
        ]
        if before != after and repo.find_started_tie_for_entry(conn, team_id) is not None:
            raise _error("该队伍已有开始或结束的团体对抗，不能修改队员或队内顺序")


def save_sheet(conn: sqlite3.Connection, tournament_id: int, payload: dict) -> dict:
    current = _sheet(conn, tournament_id)
    tournament = current["tournament"]
    _require_editable(tournament)
    if payload["base_revision"] != current["revision"]:
        raise _error("名单已被其他操作更新，请刷新后核对再保存")

    draft_teams = payload["teams"]
    draft_players = payload["players"]
    _unique([item["key"] for item in draft_teams], "队伍草稿标识")
    _unique([item["key"] for item in draft_players], "队员草稿标识")
    _unique([item["sort_order"] for item in draft_teams], "队伍正式顺序")

    existing_teams = {team["id"]: team for team in current["teams"]}
    existing_players = {player["id"]: player for player in current["players"]}
    deleted_teams = set(payload["deleted_team_ids"])
    deleted_players = set(payload["deleted_player_ids"])
    _unique(payload["deleted_team_ids"], "删除队伍")
    _unique(payload["deleted_player_ids"], "删除队员")
    if not deleted_teams.issubset(existing_teams) or not deleted_players.issubset(existing_players):
        raise _error("删除列表包含不属于本赛事的记录", 404)

    supplied_team_id_list = [item["id"] for item in draft_teams if item["id"] is not None]
    supplied_player_id_list = [item["id"] for item in draft_players if item["id"] is not None]
    _unique(supplied_team_id_list, "队伍 id")
    _unique(supplied_player_id_list, "队员 id")
    supplied_team_ids = set(supplied_team_id_list)
    supplied_player_ids = set(supplied_player_id_list)
    if not supplied_team_ids.issubset(existing_teams) or not supplied_player_ids.issubset(existing_players):
        raise _error("草稿包含不属于本赛事的记录", 404)
    if set(existing_teams) != supplied_team_ids | deleted_teams:
        raise _error("草稿遗漏了已有队伍；请显式删除后再保存", 422)
    if set(existing_players) != supplied_player_ids | deleted_players:
        raise _error("草稿遗漏了已有队员；请显式删除后再保存", 422)
    if deleted_teams & supplied_team_ids or deleted_players & supplied_player_ids:
        raise _error("同一记录不能既保留又删除", 422)

    team_by_key = {item["key"]: item for item in draft_teams}
    names = [item["display_name"].strip() for item in draft_teams]
    if any(not name for name in names):
        raise _error("队伍名称不能为空", 422)
    _unique(names, "队伍名称")
    members: dict[str, list[dict]] = {key: [] for key in team_by_key}
    for player in draft_players:
        key = player.get("team_key")
        if key is None:
            if player.get("member_order") is not None:
                raise _error("未分队队员不能设置队内序号", 422)
            continue
        if key not in team_by_key:
            raise _error("队员引用了不存在的队伍", 422)
        if player.get("member_order") is None:
            raise _error("已分队队员必须设置队内序号", 422)
        members[key].append(player)
    for key, rows in members.items():
        if not rows:
            raise _error(f"队伍「{team_by_key[key]['display_name']}」至少需要 1 名队员", 422)
        orders = [row["member_order"] for row in rows]
        _unique(orders, f"队伍「{team_by_key[key]['display_name']}」的队内序号")
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise _error(f"队伍「{team_by_key[key]['display_name']}」的队内序号必须从 1 连续排列", 422)

    with teams._roster_write_tx(conn):
        # 在取到写锁后重读，避免校验和提交之间被其它请求插入。
        locked_current = _sheet(conn, tournament_id)
        _require_editable(locked_current["tournament"])
        if payload["base_revision"] != locked_current["revision"]:
            raise _error("名单已被其他操作更新，请刷新后核对再保存")
        players.ensure_player_capacity(
            len(locked_current["players"]),
            additions=sum(player["id"] is None for player in draft_players),
            deletions=len(deleted_players),
        )
        _protect_started_team_members(conn, locked_current, draft_teams, members)
        for team_id in deleted_teams:
            if repo.find_tie_referencing_entry(conn, team_id) is not None:
                raise _error("已出现在团体对抗中的队伍不能删除")
        for team_id in deleted_teams:
            repo.delete_entry(conn, team_id)
        # 先清空存活队伍成员，跨队调换才不会触发 entry_members 的全局 UNIQUE。
        for team_id in supplied_team_ids:
            conn.execute("DELETE FROM entry_members WHERE entry_id = ?", (team_id,))
        for player_id in deleted_players:
            repo.delete_player(conn, player_id)

        player_ids: dict[str, int] = {}
        for player in draft_players:
            if player["id"] is None:
                created = repo.add_player(conn, tournament_id, player["name"], player["college"], player["rating_points"])
                player_ids[player["key"]] = created["id"]
            else:
                repo.replace_player_values(conn, player["id"], player["name"], player["college"], player["rating_points"])
                player_ids[player["key"]] = player["id"]

        team_ids: dict[str, int] = {}
        for team in draft_teams:
            if team["id"] is not None:
                repo.update_entry(conn, team["id"], team["display_name"].strip(), team["rating_points"])
                repo.update_entry_sort_order(conn, team["id"], team["sort_order"])
                team_ids[team["key"]] = team["id"]
        for team in draft_teams:
            if team["id"] is None:
                ordered = sorted(members[team["key"]], key=lambda item: item["member_order"])
                created = repo.create_entry(
                    conn, tournament_id, EventType.TEAM.value, team["display_name"].strip(),
                    team["rating_points"], [player_ids[row["key"]] for row in ordered],
                )
                repo.update_entry_sort_order(conn, created["id"], team["sort_order"])
                team_ids[team["key"]] = created["id"]
        for team in draft_teams:
            if team["id"] is not None:
                ordered = sorted(members[team["key"]], key=lambda item: item["member_order"])
                repo.replace_entry_members(conn, team_ids[team["key"]], [player_ids[row["key"]] for row in ordered])
    return _sheet(conn, tournament_id)


def unconfirm_roster(conn: sqlite3.Connection, tournament_id: int) -> dict:
    with teams._roster_write_tx(conn):
        sheet = _sheet(conn, tournament_id)
        tournament = sheet["tournament"]
        if tournament["stage"] != TournamentStage.REGISTRATION.value:
            raise _error("赛事已进入比赛阶段，不能撤销名单冻结")
        if not tournament["roster_confirmed"]:
            raise _error("名单尚未确认，无需撤销冻结")
        started = [tie for tie in repo.list_team_ties(conn, tournament_id) if tie["status"] in ("PLAYING", "FINISHED")]
        if started:
            raise _error("已有团体对抗开始或结束，不能撤销名单冻结")
        repo.unconfirm_tournament_roster(conn, tournament_id)
    return _sheet(conn, tournament_id)
