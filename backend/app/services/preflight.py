"""主裁判只读赛前检查：聚合现有事实，不改变赛事状态。"""

import sqlite3

from .. import repository as repo
from ..models import MatchStage, MatchStatus, PreflightLevel, TableStatus, TournamentMode, TournamentStage
from . import rankings as rankings_service


class PreflightError(Exception):
    def __init__(self, message: str, code: int = 404):
        super().__init__(message)
        self.code = code


def _check(
    code: str,
    title: str,
    detail: str,
    level: PreflightLevel,
    action_label: str | None = None,
    action_path: str | None = None,
) -> dict:
    return {
        "code": code,
        "title": title,
        "detail": detail,
        "level": level.value,
        "action_label": action_label,
        "action_path": action_path,
    }


def inspect_tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise PreflightError("赛事不存在")

    players = repo.list_players(conn, tournament_id)
    entries = repo.list_entries(conn, tournament_id)
    groups = repo.list_groups(conn, tournament_id)
    matches = repo.list_matches(conn, tournament_id)
    group_matches = [m for m in matches if m["stage"] == MatchStage.GROUP.value]
    knockout_matches = [m for m in matches if m["stage"] == MatchStage.KNOCKOUT.value]
    tables = repo.list_tables(conn, tournament_id)
    playing = [m for m in matches if m["status"] == MatchStatus.PLAYING.value]
    occupied = [t for t in tables if t["status"] == TableStatus.OCCUPIED.value]
    tid = tournament_id
    checks: list[dict] = []

    mode_level = PreflightLevel.READY if tournament["operation_mode"] == TournamentMode.LIVE.value else PreflightLevel.WARN
    checks.append(_check(
        "operation_mode",
        "运行模式",
        "正式赛事，演示造数入口已隔离。" if mode_level == PreflightLevel.READY else "当前是演示赛事，请勿将结果作为正式成绩发布。",
        mode_level,
        "查看赛事首页",
        f"/?tid={tid}",
    ))

    if tournament["roster_confirmed"]:
        checks.append(_check("roster", "参赛名单", f"名单已确认，共 {len(players)} 名运动员、{len(entries)} 个参赛位。", PreflightLevel.READY))
    else:
        checks.append(_check("roster", "参赛名单", "名单尚未确认，不能进入正式分赛流程。", PreflightLevel.BLOCK, "确认名单", f"/players?tid={tid}"))

    expected_members = 2 if tournament["event_type"] == "DOUBLES" else 1
    invalid_entries = [entry for entry in entries if len(entry["members"]) != expected_members]
    if not entries:
        checks.append(_check("entries", "参赛位完整性", "尚未建立参赛位。单打需一人一位，双打需两人一组。", PreflightLevel.BLOCK, "处理名单", f"/players?tid={tid}"))
    elif invalid_entries:
        checks.append(_check("entries", "参赛位完整性", f"发现 {len(invalid_entries)} 个成员数量不正确的参赛位。", PreflightLevel.BLOCK, "检查参赛位", f"/players?tid={tid}"))
    else:
        checks.append(_check("entries", "参赛位完整性", f"全部 {len(entries)} 个参赛位结构正确。", PreflightLevel.READY))

    assigned = sum(1 for entry in entries if entry["group_id"] is not None)
    if not groups:
        checks.append(_check("groups", "分组与抽签", "尚未生成小组。", PreflightLevel.BLOCK, "前往分组", f"/players?tid={tid}"))
    elif assigned != len(entries):
        checks.append(_check("groups", "分组与抽签", f"已有 {len(groups)} 个小组，但仍有 {len(entries) - assigned} 个参赛位未分组。", PreflightLevel.BLOCK, "检查分组", f"/players?tid={tid}"))
    else:
        checks.append(_check("groups", "分组与抽签", f"{len(groups)} 个小组、{assigned} 个参赛位均已落位。", PreflightLevel.READY))

    group_schedule_generated = tournament["stage"] != TournamentStage.REGISTRATION.value
    if not group_matches and not group_schedule_generated:
        checks.append(_check("group_schedule", "小组赛程", "小组循环赛尚未生成。", PreflightLevel.BLOCK, "生成小组比赛", f"/players?tid={tid}"))
    elif not group_matches:
        checks.append(_check("group_schedule", "小组赛程", "小组阶段已生成；各组无需产生循环赛场次。", PreflightLevel.READY, "查看小组排名", f"/rankings?tid={tid}"))
    else:
        unfinished_group = sum(1 for match in group_matches if match["status"] != MatchStatus.FINISHED.value)
        checks.append(_check(
            "group_schedule",
            "小组赛程",
            f"已生成 {len(group_matches)} 场；{'全部结束' if unfinished_group == 0 else f'仍有 {unfinished_group} 场未结束'}。",
            PreflightLevel.READY if unfinished_group == 0 else PreflightLevel.WARN,
            "进入比赛控制台" if unfinished_group else "查看小组排名",
            f"/{'console' if unfinished_group else 'rankings'}?tid={tid}",
        ))

    occupied_ids = {table["id"] for table in occupied}
    playing_table_ids = [match.get("table_id") for match in playing]
    table_consistent = (
        len(tables) == tournament["table_count"]
        and all(table_id is not None for table_id in playing_table_ids)
        and len(set(playing_table_ids)) == len(playing_table_ids)
        and set(playing_table_ids) == occupied_ids
    )
    if table_consistent:
        checks.append(_check("tables", "球台状态", f"{len(tables)} 张球台状态一致，当前占用 {len(occupied)} 张。", PreflightLevel.READY, "查看现场", f"/console?tid={tid}"))
    else:
        checks.append(_check("tables", "球台状态", "球台配置、占用状态与进行中比赛不一致，需要先修复。", PreflightLevel.BLOCK, "检查比赛现场", f"/console?tid={tid}"))

    ambiguous_groups = 0
    needs_scores = 0
    if group_schedule_generated:
        for group in rankings_service.get_rankings(conn, tournament_id):
            complete = group["finished_matches"] == group["total_matches"]
            if complete and group["ambiguous_qualification"]:
                ambiguous_groups += 1
                if group["needs_point_scores"]:
                    needs_scores += 1
    if ambiguous_groups:
        detail = f"{ambiguous_groups} 个已完赛小组仍无法确定晋级；其中 {needs_scores} 个需要先补录关键小分。"
        checks.append(_check("qualification", "晋级判定", detail, PreflightLevel.BLOCK, "处理小组排名", f"/rankings?tid={tid}"))
    else:
        checks.append(_check("qualification", "晋级判定", "当前没有已完赛但尚未解决的晋级线并列。", PreflightLevel.READY, "查看排名", f"/rankings?tid={tid}"))

    unfinished_group = sum(1 for match in group_matches if match["status"] != MatchStatus.FINISHED.value)
    if knockout_matches:
        checks.append(_check("knockout", "淘汰赛衔接", f"淘汰签已生成，共 {len(knockout_matches)} 场。", PreflightLevel.READY, "查看淘汰赛", f"/knockout?tid={tid}"))
    elif group_schedule_generated and unfinished_group == 0 and ambiguous_groups == 0:
        checks.append(_check("knockout", "淘汰赛衔接", "小组赛已结束且晋级明确，可以生成淘汰签。", PreflightLevel.READY, "生成淘汰赛", f"/knockout?tid={tid}"))
    else:
        checks.append(_check("knockout", "淘汰赛衔接", "完成全部小组赛并处理晋级线并列后，才能生成淘汰签。", PreflightLevel.WARN, "查看当前进度", f"/rankings?tid={tid}"))

    checks.append(_check(
        "rules",
        "比赛规则",
        f"{tournament['games_to_win'] * 2 - 1} 局 {tournament['games_to_win']} 胜 · 每局 {tournament['points_to_win']} 分 · 小组按胜场、净胜局、赛事积分排序，特殊同分交主裁处理。",
        PreflightLevel.READY,
    ))

    blocker_count = sum(item["level"] == PreflightLevel.BLOCK.value for item in checks)
    warning_count = sum(item["level"] == PreflightLevel.WARN.value for item in checks)
    overall = PreflightLevel.BLOCK if blocker_count else (PreflightLevel.WARN if warning_count else PreflightLevel.READY)
    return {
        "tournament": tournament,
        "overall": overall.value,
        "ready_count": len(checks) - blocker_count - warning_count,
        "warning_count": warning_count,
        "blocker_count": blocker_count,
        "metrics": {
            "players": len(players),
            "entries": len(entries),
            "groups": len(groups),
            "tables": len(tables),
            "matches": len(matches),
            "playing": len(playing),
        },
        "checks": checks,
    }
