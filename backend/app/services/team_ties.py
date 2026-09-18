"""团体对抗（TeamTie）与单盘骨架（TeamRubber）服务。

术语：
- TeamTie：一场"A 队 vs B 队"的团体对抗，计分单位是"赢了几盘"；
- TeamRubber：对抗里的一盘（单打盘或双打盘），A3 只记录"这盘需要几个出场位置"。

A3 明确不做的事（避免后来人误以为漏了实现）：
1. 不为任何一盘创建 matches 行，team_rubbers.match_id 永远是 NULL。
   原因：一盘双打需要两名选手同时上场，而 entry_members 对 player_id 全局唯一，
   把一盘做成普通 Match 会让"同一名选手既在队伍 Entry 里、又在双打盘 Entry 里"
   直接违反唯一约束；并且 scheduling._match_member_ids() 会把 Entry 的全部成员
   标记为占用，用它算球台会一次性占满整队。
   真正的"盘 → 球台/赛程"适配器属于 A4，届时 match_id 这一列才启用。
2. 不实现比分状态机（WAITING → PLAYING → FINISHED）、不做赛制取胜判定、
   不生成对抗对阵（抽签/循环编排）、不参与排程与 ETA。
3. 阶段门禁故意留空：TEAM 赛事目前没有任何 API 能把 stage 从 REGISTRATION
   推进到 GROUP_STAGE（generate_group_matches / generate_knockout 都会拒绝团体赛），
   若在这里要求"必须已开赛"，就等于永远无法创建对抗。阶段门禁必须与 A4 的
   团体赛排程一起设计，A3 只校验赛事是 TEAM 项目以及对抗双方合法。
"""

import json
import sqlite3

from .. import repository as repo
from ..domain import team_formats
from ..domain.team_formats import TeamFormatError
from ..models import EventType, MatchStage, TeamRubberStatus

TIE_STAGES = (MatchStage.GROUP.value, MatchStage.KNOCKOUT.value)


class TeamTieError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TeamTieError("赛事不存在", 404)
    return tournament


def _team_tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = _tournament(conn, tournament_id)
    if tournament["event_type"] != EventType.TEAM.value:
        raise TeamTieError(
            f"当前赛事项目是 {tournament['event_type']}，只有团体赛（TEAM）有团体对抗", 409
        )
    return tournament


def _team_entry(conn: sqlite3.Connection, tournament_id: int, entry_id: int, label: str) -> dict:
    entry = repo.get_entry(conn, entry_id)
    if entry is None or entry["tournament_id"] != tournament_id:
        raise TeamTieError(f"{label}队伍不存在或不属于本赛事", 404)
    if entry["entry_type"] != EventType.TEAM.value:
        raise TeamTieError(f"{label}参赛实体不是团体队伍", 409)
    return entry


def _rubber_out(row: dict) -> dict:
    """DB 行 → 输出 DTO：位置需求从 JSON 文本还原成字符串列表。"""
    out = dict(row)
    for key in ("home_slots_json", "away_slots_json"):
        try:
            value = json.loads(out.pop(key))
        except json.JSONDecodeError:
            raise TeamTieError(f"盘 #{row['id']} 的位置数据已损坏，无法解析", 500) from None
        out[key.replace("_json", "")] = value if isinstance(value, list) else []
    return out


def _tie_with_rubbers(conn: sqlite3.Connection, tie: dict) -> dict:
    out = dict(tie)
    out["rubbers"] = [_rubber_out(r) for r in repo.list_team_rubbers(conn, tie["id"])]
    return out


def get_team_tie(conn: sqlite3.Connection, tournament_id: int, tie_id: int) -> dict:
    _tournament(conn, tournament_id)
    tie = repo.get_team_tie(conn, tie_id)
    if tie is None or tie["tournament_id"] != tournament_id:
        raise TeamTieError("团体对抗不存在", 404)
    return _tie_with_rubbers(conn, tie)


def list_team_ties(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    _tournament(conn, tournament_id)
    return repo.list_team_ties(conn, tournament_id)


def create_team_tie(
    conn: sqlite3.Connection,
    tournament_id: int,
    entry_a_id: int,
    entry_b_id: int,
    stage: str = MatchStage.GROUP.value,
    group_id: int | None = None,
    round_num: int = 1,
    match_index: int | None = None,
) -> dict:
    """建立一场团体对抗（不生成任何 Match，也不生成盘骨架）。"""
    _team_tournament(conn, tournament_id)
    if entry_a_id == entry_b_id:
        raise TeamTieError("同一支队伍不能和自己对抗", 422)
    if stage not in TIE_STAGES:
        raise TeamTieError(f"对抗赛段只能是 {TIE_STAGES} 之一", 422)
    if not isinstance(round_num, int) or isinstance(round_num, bool) or round_num < 1:
        raise TeamTieError("轮次必须是不小于 1 的整数", 422)
    if match_index is not None and (
        not isinstance(match_index, int) or isinstance(match_index, bool) or match_index < 1
    ):
        raise TeamTieError("场序必须是不小于 1 的整数", 422)
    if group_id is not None:
        if stage != MatchStage.GROUP.value:
            raise TeamTieError("只有小组赛段的对抗才能挂在小组上", 422)
        group = repo.get_group(conn, group_id)
        if group is None or group["tournament_id"] != tournament_id:
            raise TeamTieError("小组不存在或不属于本赛事", 404)

    _team_entry(conn, tournament_id, entry_a_id, "主队")
    _team_entry(conn, tournament_id, entry_b_id, "客队")

    tie = repo.create_team_tie(
        conn,
        tournament_id,
        stage,
        group_id,
        round_num,
        match_index,
        entry_a_id,
        entry_b_id,
    )
    conn.commit()
    return tie


def build_rubber_skeleton(
    conn: sqlite3.Connection,
    tournament_id: int,
    tie_id: int,
    format_code: str,
    replace: bool = False,
) -> dict:
    """按注册表里的赛制为一场对抗生成盘骨架，并把赛制固化到该对抗上。

    - 赛制必须来自 domain/team_formats.py 的生产注册表；A3 的注册表是空的，
      所以现在任何调用都会得到 422——这是有意为之：规则未冻结就不生成规则。
    - 已经生成过骨架时：replace=False → 409；replace=True 只在"所有盘都还没开始"
      （status 仍是 PENDING 且 match_id 为 NULL）时允许重建，否则 409。
    - 生成的所有盘都是 PENDING 且 match_id=NULL。
    """
    _team_tournament(conn, tournament_id)
    tie = repo.get_team_tie(conn, tie_id)
    if tie is None or tie["tournament_id"] != tournament_id:
        raise TeamTieError("团体对抗不存在", 404)

    try:
        spec = team_formats.get_format_spec(format_code)
    except TeamFormatError as exc:
        raise TeamTieError(str(exc), 422) from None

    existing = repo.list_team_rubbers(conn, tie_id)
    if existing:
        if not replace:
            raise TeamTieError(
                f"该对抗已生成 {len(existing)} 盘骨架，如需重来请显式要求重建", 409
            )
        started = [
            r for r in existing
            if r["status"] != TeamRubberStatus.PENDING.value or r["match_id"] is not None
        ]
        if started:
            raise TeamTieError("对抗已有开打的盘，不能重建骨架", 409)
        repo.delete_team_rubbers_for_tie(conn, tie_id)

    skeleton = team_formats.build_rubber_skeleton(spec)
    for item in skeleton:
        repo.create_team_rubber(
            conn,
            tie_id,
            item["sequence"],
            item["rubber_type"],
            json.dumps(item["home_slots"], ensure_ascii=False),
            json.dumps(item["away_slots"], ensure_ascii=False),
        )
    repo.set_team_tie_format(
        conn, tie_id, spec.code, spec.version, team_formats.dump_snapshot(spec)
    )
    conn.commit()

    updated = repo.get_team_tie(conn, tie_id)
    return _tie_with_rubbers(conn, updated)
