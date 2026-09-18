"""团体赛 Runtime Engine（A4.1）：阵容绑定 → 盘状态机 → 对抗自动计分与提前结束。

状态机（一盘 TeamRubber）：

    PENDING ──(提交合法 lineup)──▶ READY ──(start)──▶ PLAYING ──(score)──▶ FINISHED
       │                            │
       └──────── 对抗被一方提前结束（达到 target_wins）────────▶ SKIPPED

对抗（TeamTie）：

    WAITING ──(第一盘 start)──▶ PLAYING ──(一方盘数 >= target_wins)──▶ FINISHED

刻意保持的边界（与"正式团体赛制尚未冻结"一致，不要在后续批次前擅自收紧）：

1. **只记大比分**：盘比分按赛事的 `games_to_win` 校验，**复用** `services/scores.py`
   的同一套规则（不复制第二份比分规则）；不建逐局小比分表。
2. **不强制盘序**：`sequence` 只用于展示与骨架；正式赛制若要求严格顺序，后续通过
   权限（`can_start`）扩展，本版不加未冻结规则。
3. **阵容只做通用硬约束**：选手属于本队、队伍在赛、盘未结束。不实现"最多打一盘 / 不能兼项 /
   必须一单一双"等未冻结规则。
4. **串行执行**：一个 TeamTie 同时最多一盘 PLAYING，因此提前结束时不会残留其它进行中的盘。
5. **不接 scheduler / ETA**：一盘是否占球台、能否多盘并行都还没冻结。
6. **不做异常结果与改分**：只有正常比分闭环（弃权/未到/取消资格与 revise 留给后续批次）。

对抗总分 `team_ties.team_a_score / team_b_score` 一律由后端按 FINISHED 的盘**重算**写入，
不存在"客户端直接改对抗比分"的接口（避免两个真相源）。

## 并发与原子性（Reviewer P1/P2）

FastAPI 每个请求使用独立 SQLite 连接，"先 SELECT 判断、再无条件 UPDATE"不是原子状态迁移：
两个并发请求可以同时通过校验再依次写入，从而绕过"最多一盘 PLAYING / 不允许改分"等约束。因此：

1. 所有写操作都把 **read-check-write 放进一个 `BEGIN IMMEDIATE` 写事务**（`_write_tx`）：
   拿到写锁后再读状态，天然把同一对抗的并发请求串行化；锁等待超时（另一个请求正在处理）
   返回可读的 409 而不是 500。
2. 写入本身是**带预期旧状态的条件更新**并检查 rowcount（`repository.mark_team_rubber_*`）：
   即使有人绕过事务，PLAYING 也不会被写回 READY、FINISHED 也不会被二次结算覆盖。
3. "同一对抗同时最多一盘 PLAYING"等跨行不变量**在事务内、任何写入之前**校验。

## 名单与阵容的一致性

- 提交 lineup 时校验"选手属于本队、队伍在赛"；**开始一盘时再次原子校验已保存的 lineup**
  （`lineup_valid`）：读盘后若队员已被移出名单或队伍已退赛，start 返回 409 并要求重新提交阵容
  （盘仍是 READY，可以重新提交）。
- 队伍一旦有对抗进入 PLAYING/FINISHED，**队员名单冻结**（`services/teams.py` 拒绝改 member_ids）：
  已开赛的对抗不会因为中途换人而让"不属于本队"的选手继续上场。改名与积分不受影响。
"""

import json
import sqlite3
from contextlib import contextmanager

from .. import repository as repo
from ..domain import team_formats
from ..domain.team_formats import TeamFormatError
from ..models import (
    EventType,
    MatchStage,
    TeamRubberStatus,
    TeamRubberType,
    TeamSide,
    TeamTieStatus,
)
from .scores import ScoreError, validate_aggregate_score
from .team_ties import TeamTieError, _team_tournament  # 同包共享赛事/项目前置校验
from .teams import ENTRY_STATUS_ACTIVE

#: 每边需要的上场人数直接来自赛制领域定义（SINGLES=1 / DOUBLES=2），不在这里写第二份。
SLOTS_PER_SIDE = team_formats.SLOTS_PER_SIDE

LINEUP_EDITABLE = (TeamRubberStatus.PENDING.value, TeamRubberStatus.READY.value)


class TeamRuntimeError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


@contextmanager
def _write_tx(conn: sqlite3.Connection):
    """把一次 Runtime 写操作的"读-判断-写"整体放进写事务。

    `BEGIN IMMEDIATE` 立刻取写锁：同一对抗的并发请求会被串行化，后来者读到的是前一个
    请求已提交的状态，因此状态机守卫不会被并发绕过。异常一律回滚（不留半成品状态）。
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "within a transaction" in message:
            # 调用方漏了 commit，属于内部错误（正常请求路径每个请求一个干净连接）。
            raise TeamRuntimeError(f"内部错误：Runtime 写事务嵌套（{exc}）", 500) from None
        raise TeamRuntimeError(
            f"该对抗正在被另一个请求处理，请稍后重试（{exc}）", 409
        ) from None
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    try:
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        raise TeamRuntimeError(f"写入冲突，请稍后重试（{exc}）", 409) from None



# ---------------------------------------------------------------- 读取与解析

def _tie(conn: sqlite3.Connection, tournament_id: int, tie_id: int) -> dict:
    """取对抗；赛事/项目校验复用 team_ties 的实现，但统一成本模块的错误类型。"""
    try:
        _team_tournament(conn, tournament_id)
    except TeamTieError as exc:
        raise TeamRuntimeError(str(exc), exc.code) from None
    tie = repo.get_team_tie(conn, tie_id)
    if tie is None or tie["tournament_id"] != tournament_id:
        raise TeamRuntimeError("团体对抗不存在", 404)
    return tie


def _rubber(conn: sqlite3.Connection, tie_id: int, rubber_id: int) -> dict:
    rubber = repo.get_team_rubber(conn, rubber_id)
    if rubber is None or rubber["team_tie_id"] != tie_id:
        raise TeamRuntimeError("盘不存在或不属于该对抗", 404)
    return rubber


def _load_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise TeamRuntimeError("该盘的阵容数据已损坏，无法解析", 500) from None
    if not isinstance(value, list):
        return []
    return [pid for pid in value if isinstance(pid, int)]


def _load_slots(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise TeamRuntimeError("该盘的位置数据已损坏，无法解析", 500) from None
    return value if isinstance(value, list) else []


def _target_wins(tie: dict) -> int | None:
    """获胜所需盘数只从赛制快照读取：既不 hardcode，也不用 (len(rubbers)+1)//2 推算。"""
    if not tie.get("format_snapshot"):
        return None
    try:
        return team_formats.load_snapshot(tie["format_snapshot"]).rubbers_to_win
    except TeamFormatError:
        return None


def _require_target_wins(tie: dict) -> int:
    target = _target_wins(tie)
    if target is None:
        raise TeamRuntimeError("该对抗缺少可用的赛制快照，无法判断获胜所需盘数", 409)
    return target


def _playing_rubbers(rubbers: list[dict]) -> list[dict]:
    return [r for r in rubbers if r["status"] == TeamRubberStatus.PLAYING.value]


def _winner_side(tie: dict, rubber: dict) -> str | None:
    winner = rubber.get("winner_entry_id")
    if winner is None:
        return None
    if winner == tie["entry_a_id"]:
        return TeamSide.HOME.value
    if winner == tie["entry_b_id"]:
        return TeamSide.AWAY.value
    return None


def _player_name(players: dict[int, dict], player_id: int) -> str:
    player = players.get(player_id)
    # 名单绑定后选手仍可能被删除（entry_members 是级联的），兜底成技术性占位而不是编造姓名。
    return player["name"] if player else f"#{player_id}"


# ---------------------------------------------------------------- 权限（B 直接消费）

def _rubber_permissions(
    tie: dict, rubber: dict, has_playing: bool, lineup_valid: bool
) -> dict:
    tie_open = tie["status"] != TeamTieStatus.FINISHED.value
    status = rubber["status"]
    can_edit = tie_open and status in LINEUP_EDITABLE
    return {
        "can_edit_lineup": can_edit,
        # 本版"提交 lineup 即确认"（PENDING → READY），没有单独的确认步骤；
        # 该字段与 can_edit_lineup 同义，保留给 UI 的"确认阵容"按钮。
        "can_confirm_lineup": can_edit,
        # 阵容失效（队员已不在名单中 / 队伍已退赛）时不能开始：权限与服务端守卫必须一致。
        "can_start": (
            tie_open
            and status == TeamRubberStatus.READY.value
            and not has_playing
            and lineup_valid
        ),
        "can_record_score": status == TeamRubberStatus.PLAYING.value,
        "can_revise_score": False,  # A4.1 不做改分
    }


def _tie_permissions(rubbers: list[dict]) -> dict:
    """对抗级权限 = 各盘权限的汇总（B 的按钮直接消费，不需要前端自己推状态机）。"""
    return {
        "can_edit_lineup": any(r["permissions"]["can_edit_lineup"] for r in rubbers),
        "can_confirm_lineup": any(r["permissions"]["can_confirm_lineup"] for r in rubbers),
        "can_start": any(r["permissions"]["can_start"] for r in rubbers),
        "can_record_score": any(r["permissions"]["can_record_score"] for r in rubbers),
        "can_revise_score": False,  # A4.1 不做改分
    }


# ---------------------------------------------------------------- 视图组装

def _lineup_options(tie: dict, rubber: dict, entry: dict, players: dict[int, dict]) -> list[dict]:
    """某一边的候选阵容：只执行通用硬约束（本队队员 + 队伍在赛 + 本盘未结束）。"""
    options = []
    for member in entry["members"]:
        reason = None
        if tie["status"] == TeamTieStatus.FINISHED.value:
            reason = "对抗已结束"
        elif entry["status"] != ENTRY_STATUS_ACTIVE:
            reason = "队伍已退出赛事"
        elif rubber["status"] not in LINEUP_EDITABLE:
            reason = "本盘已开始或已结束，阵容已锁定"
        options.append(
            {
                "player_id": member["player_id"],
                "name": _player_name(players, member["player_id"]),
                "available": reason is None,
                "unavailable_reason": reason,
            }
        )
    return options


def _lineup_members(entry: dict) -> set[int]:
    return {m["player_id"] for m in entry["members"]}


def _saved_lineup(rubber: dict) -> tuple[list[int], list[int]]:
    return _load_ids(rubber.get("home_player_ids_json")), _load_ids(rubber.get("away_player_ids_json"))


def _lineup_invalid_reason(
    tie: dict, rubber: dict, entry_a: dict, entry_b: dict
) -> str | None:
    """已保存的 lineup 是否仍然有效（开始一盘前必须原子重校验）。

    返回 None 表示有效；否则返回可展示的失效原因。失效只针对"已经保存过阵容"的盘：
    还没绑定阵容的 PENDING 盘由"未就绪"处理，不走这里。
    """
    home_ids, away_ids = _saved_lineup(rubber)
    if not home_ids and not away_ids:
        return None
    expected = SLOTS_PER_SIDE[rubber["rubber_type"]]
    if len(home_ids) != expected or len(away_ids) != expected:
        return "本盘阵容人数与盘型不符，请重新提交阵容"
    for label, entry, ids in (("主队", entry_a, home_ids), ("客队", entry_b, away_ids)):
        if entry["status"] != ENTRY_STATUS_ACTIVE:
            return f"{label}「{entry['display_name']}」已退出赛事，不能开始本盘"
        members = _lineup_members(entry)
        missing = [pid for pid in ids if pid not in members]
        if missing:
            return f"本盘{label}阵容已失效：有队员已不在队伍名单中，请重新提交阵容"
    return None


def _rubber_view(
    tie: dict, rubber: dict, entry_a: dict, entry_b: dict, players: dict[int, dict], has_playing: bool
) -> dict:
    home_ids = _load_ids(rubber.get("home_player_ids_json"))
    away_ids = _load_ids(rubber.get("away_player_ids_json"))
    invalid_reason = _lineup_invalid_reason(tie, rubber, entry_a, entry_b)
    return {
        "id": rubber["id"],
        "team_tie_id": rubber["team_tie_id"],
        "sequence": rubber["sequence"],
        "rubber_type": rubber["rubber_type"],
        "status": rubber["status"],
        "home_slots": _load_slots(rubber["home_slots_json"]),
        "away_slots": _load_slots(rubber["away_slots_json"]),
        "home_player_ids": home_ids,
        "away_player_ids": away_ids,
        "home_players": [_player_name(players, pid) for pid in home_ids],
        "away_players": [_player_name(players, pid) for pid in away_ids],
        "home_score": rubber.get("home_score"),
        "away_score": rubber.get("away_score"),
        "winner_side": _winner_side(tie, rubber),
        "winner_entry_id": rubber.get("winner_entry_id"),
        # A4.1 仍然不创建普通 Match：这一列继续为 NULL（A3 已确认的架构边界）。
        "match_id": rubber.get("match_id"),
        # 已保存阵容是否仍满足"选手属于本队 + 队伍在赛"；失效时 start 会 409，权限也不放行。
        "lineup_valid": invalid_reason is None,
        "lineup_invalid_reason": invalid_reason,
        "permissions": _rubber_permissions(tie, rubber, has_playing, invalid_reason is None),
        "lineup_options": {
            "home": _lineup_options(tie, rubber, entry_a, players),
            "away": _lineup_options(tie, rubber, entry_b, players),
        },
        "created_at": rubber["created_at"],
        "started_at": rubber.get("started_at"),
        "finished_at": rubber.get("finished_at"),
    }


def _team_summary(entry: dict) -> dict:
    return {
        "entry_id": entry["id"],
        "display_name": entry["display_name"],
        "status": entry["status"],
        # 成员直接内嵌，避免 B 为了显示一支队伍再发一堆请求。
        "members": entry["members"],
    }


def _format_view(tie: dict, target_wins: int | None) -> dict:
    display_name = None
    if tie.get("format_snapshot"):
        try:
            display_name = team_formats.load_snapshot(tie["format_snapshot"]).display_name
        except TeamFormatError:
            display_name = None
    return {
        "code": tie.get("format_code"),
        "version": tie.get("format_version"),
        "display_name": display_name,
        "rubbers_to_win": target_wins,
    }


def runtime_view(conn: sqlite3.Connection, tournament_id: int, tie_id: int) -> dict:
    """读取一场对抗的完整运行态（也是所有写操作的返回值）。"""
    tie = _tie(conn, tournament_id, tie_id)
    return _build_view(conn, tie)


def _build_view(conn: sqlite3.Connection, tie: dict) -> dict:
    entry_a = repo.get_entry(conn, tie["entry_a_id"])
    entry_b = repo.get_entry(conn, tie["entry_b_id"])
    if entry_a is None or entry_b is None:
        raise TeamRuntimeError("对抗的参赛队伍已不存在", 409)
    players = {p["id"]: p for p in repo.list_players(conn, tie["tournament_id"])}
    rubbers = repo.list_team_rubbers(conn, tie["id"])
    has_playing = bool(_playing_rubbers(rubbers))
    target_wins = _target_wins(tie)
    rubber_views = [
        _rubber_view(tie, rubber, entry_a, entry_b, players, has_playing) for rubber in rubbers
    ]
    return {
        # ---- A3 存储字段：保持原有命名，避免破坏已消费方 ----
        "id": tie["id"],
        "tournament_id": tie["tournament_id"],
        "stage": tie["stage"],
        "group_id": tie["group_id"],
        "round": tie["round"],
        "match_index": tie["match_index"],
        "entry_a_id": tie["entry_a_id"],
        "entry_b_id": tie["entry_b_id"],
        "team_a_score": tie["team_a_score"],
        "team_b_score": tie["team_b_score"],
        "winner_entry_id": tie["winner_entry_id"],
        "status": tie["status"],
        "format_code": tie.get("format_code"),
        "format_version": tie.get("format_version"),
        "format_snapshot": tie.get("format_snapshot"),
        "called_at": tie.get("called_at"),
        "started_at": tie.get("started_at"),
        "finished_at": tie.get("finished_at"),
        "created_at": tie["created_at"],
        # ---- Runtime 契约（B 消费；字段名与 docs/TEAM_RUNTIME_CONTRACT.md 一致）----
        "home_team": _team_summary(entry_a),
        "away_team": _team_summary(entry_b),
        "home_score": tie["team_a_score"],
        "away_score": tie["team_b_score"],
        "target_wins": target_wins,
        "format": _format_view(tie, target_wins),
        "rubbers": rubber_views,
        "permissions": _tie_permissions(rubber_views),
    }


def lineup_options(
    conn: sqlite3.Connection, tournament_id: int, tie_id: int, rubber_id: int
) -> dict:
    """某一盘两边的候选阵容（与 runtime view 内嵌的 lineup_options 同源）。"""
    tie = _tie(conn, tournament_id, tie_id)
    rubber = _rubber(conn, tie_id, rubber_id)
    entry_a = repo.get_entry(conn, tie["entry_a_id"])
    entry_b = repo.get_entry(conn, tie["entry_b_id"])
    if entry_a is None or entry_b is None:
        raise TeamRuntimeError("对抗的参赛队伍已不存在", 409)
    players = {p["id"]: p for p in repo.list_players(conn, tie["tournament_id"])}
    return {
        "home": _lineup_options(tie, rubber, entry_a, players),
        "away": _lineup_options(tie, rubber, entry_b, players),
    }


# ---------------------------------------------------------------- 写操作

def _validate_side_ids(
    conn: sqlite3.Connection,
    entry: dict,
    player_ids: list[int],
    rubber_type: str,
    side_label: str,
) -> None:
    expected = SLOTS_PER_SIDE[rubber_type]
    if len(player_ids) != expected:
        raise TeamRuntimeError(
            f"{side_label}需要 {expected} 名队员"
            f"（{'单打' if rubber_type == TeamRubberType.SINGLES.value else '双打'}盘），"
            f"实际提交 {len(player_ids)} 名",
            422,
        )
    if len(set(player_ids)) != len(player_ids):
        raise TeamRuntimeError(f"{side_label}不能重复安排同一名队员", 422)
    member_ids = {m["player_id"] for m in entry["members"]}
    for player_id in player_ids:
        if not isinstance(player_id, int) or isinstance(player_id, bool):
            raise TeamRuntimeError("队员必须是选手 id", 422)
        if repo.get_player(conn, player_id) is None:
            raise TeamRuntimeError(f"选手 {player_id} 不存在", 404)
        if player_id not in member_ids:
            raise TeamRuntimeError(
                f"选手 {player_id} 不属于「{entry['display_name']}」，不能代表该队上场", 409
            )


def set_lineup(
    conn: sqlite3.Connection,
    tournament_id: int,
    tie_id: int,
    rubber_id: int,
    home_player_ids: list[int],
    away_player_ids: list[int],
) -> dict:
    """提交一盘的实际参赛人；合法阵容写入后 PENDING → READY（已 READY 则保持 READY）。

    整个"读状态 → 校验 → 写"在写事务内完成；写入是条件更新（只允许 PENDING/READY → READY），
    因此与并发的 start 竞争时不会把 PLAYING 反向写回 READY。
    """
    with _write_tx(conn):
        tie = _tie(conn, tournament_id, tie_id)
        rubber = _rubber(conn, tie_id, rubber_id)
        if tie["status"] == TeamTieStatus.FINISHED.value:
            raise TeamRuntimeError("对抗已结束，不能再调整阵容", 409)
        if rubber["status"] not in LINEUP_EDITABLE:
            raise TeamRuntimeError("本盘已开始或已结束，阵容已锁定", 409)

        entry_a = repo.get_entry(conn, tie["entry_a_id"])
        entry_b = repo.get_entry(conn, tie["entry_b_id"])
        if entry_a is None or entry_b is None:
            raise TeamRuntimeError("对抗的参赛队伍已不存在", 409)
        for entry in (entry_a, entry_b):
            if entry["status"] != ENTRY_STATUS_ACTIVE:
                raise TeamRuntimeError(
                    f"队伍「{entry['display_name']}」已退出赛事，不能安排阵容", 409
                )

        _validate_side_ids(conn, entry_a, home_player_ids or [], rubber["rubber_type"], "主队")
        _validate_side_ids(conn, entry_b, away_player_ids or [], rubber["rubber_type"], "客队")

        updated = repo.set_team_rubber_lineup(
            conn,
            rubber_id,
            json.dumps(list(home_player_ids), ensure_ascii=False),
            json.dumps(list(away_player_ids), ensure_ascii=False),
        )
        if not updated:
            # 条件更新没命中：盘的旧状态在事务内已经变了（例如并发 start / 对抗结束）。
            raise TeamRuntimeError("本盘状态已变化，请刷新后重试", 409)
    return _build_view(conn, repo.get_team_tie(conn, tie_id))


def start_rubber(
    conn: sqlite3.Connection, tournament_id: int, tie_id: int, rubber_id: int
) -> dict:
    """READY → PLAYING；同一对抗同时只允许一盘进行中。

    开始前会**原子重新校验已保存的阵容**（`lineup_valid`）：队员已被移出名单、或队伍已退赛时
    拒绝开始（409），盘仍是 READY，可以重新提交阵容后再开始。
    """
    with _write_tx(conn):
        tie = _tie(conn, tournament_id, tie_id)
        rubber = _rubber(conn, tie_id, rubber_id)
        if tie["status"] == TeamTieStatus.FINISHED.value:
            raise TeamRuntimeError("对抗已结束，不能再开始新的盘", 409)
        if rubber["status"] == TeamRubberStatus.PENDING.value:
            raise TeamRuntimeError("请先提交本盘的合法阵容，再开始比赛", 409)
        if rubber["status"] != TeamRubberStatus.READY.value:
            raise TeamRuntimeError(
                "本盘已经开始或已经结束，不能重复开始"
                if rubber["status"] == TeamRubberStatus.PLAYING.value
                else "本盘已跳过，不能开始",
                409,
            )

        entry_a = repo.get_entry(conn, tie["entry_a_id"])
        entry_b = repo.get_entry(conn, tie["entry_b_id"])
        if entry_a is None or entry_b is None:
            raise TeamRuntimeError("对抗的参赛队伍已不存在", 409)
        invalid = _lineup_invalid_reason(tie, rubber, entry_a, entry_b)
        if invalid:
            raise TeamRuntimeError(f"{invalid}（本盘仍未开始，可重新提交阵容）", 409)

        others = _playing_rubbers(repo.list_team_rubbers(conn, tie_id))
        if others:
            raise TeamRuntimeError(
                f"同一对抗同时只能进行一盘（第 {others[0]['sequence']} 盘正在进行中）", 409
            )

        if not repo.mark_team_rubber_playing(conn, rubber_id):
            raise TeamRuntimeError("本盘状态已变化，请刷新后重试", 409)
        if tie["status"] == TeamTieStatus.WAITING.value:
            repo.mark_team_tie_playing(conn, tie_id)
    return _build_view(conn, repo.get_team_tie(conn, tie_id))


def record_rubber_score(
    conn: sqlite3.Connection,
    tournament_id: int,
    tie_id: int,
    rubber_id: int,
    home_score: int,
    away_score: int,
) -> dict:
    """PLAYING 的盘录大比分 → 盘 FINISHED → 对抗总分重算 → 达到 target_wins 时提前结束。

    所有校验（包括"同一对抗不得有多盘 PLAYING"）都在任何写入之前完成；写事务保证
    "读-判断-写"原子，条件更新保证并发重复录分不会覆盖已结算的比分（本版不支持改分）。
    """
    with _write_tx(conn):
        tie = _tie(conn, tournament_id, tie_id)
        rubber = _rubber(conn, tie_id, rubber_id)
        if tie["status"] == TeamTieStatus.FINISHED.value:
            raise TeamRuntimeError("对抗已结束，不能再录分", 409)
        if rubber["status"] != TeamRubberStatus.PLAYING.value:
            raise TeamRuntimeError(
                "请先开始本盘再录分"
                if rubber["status"] in LINEUP_EDITABLE
                else (
                    "本盘已经结束，本版不支持改分"
                    if rubber["status"] == TeamRubberStatus.FINISHED.value
                    else "本盘已跳过，不能录分"
                ),
                409,
            )

        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise TeamRuntimeError("赛事不存在", 404)
        try:
            # 复用个人赛同一套大比分规则（胜局数必须等于 games_to_win、不能平局、不能负数）。
            validate_aggregate_score(home_score, away_score, tournament["games_to_win"])
        except ScoreError as exc:
            # 盘比分只来自 payload，不存在"与当前状态冲突"的语义，因此统一按 422 返回。
            raise TeamRuntimeError(str(exc), 422) from None

        target_wins = _require_target_wins(tie)
        rubbers = repo.list_team_rubbers(conn, tie_id)
        # 不变量检查必须在任何写入之前：串行规则保证不会出现第二盘 PLAYING，
        # 真出现说明数据被绕过接口改写，此时直接拒绝，不留下"已改成 FINISHED 的脏状态"。
        others_playing = [
            r for r in _playing_rubbers(rubbers) if r["id"] != rubber_id
        ]
        if others_playing:
            raise TeamRuntimeError(
                f"检测到同一对抗有第 {others_playing[0]['sequence']} 盘也在进行中，拒绝自动结算", 409
            )

        winner_entry_id = tie["entry_a_id"] if home_score > away_score else tie["entry_b_id"]
        if not repo.mark_team_rubber_finished(
            conn, rubber_id, home_score, away_score, winner_entry_id
        ):
            # 条件更新未命中：说明该盘已被另一个并发请求结算（本版不支持改分）。
            raise TeamRuntimeError("本盘已经结束，本版不支持改分", 409)

        finished = [
            r for r in repo.list_team_rubbers(conn, tie_id)
            if r["status"] == TeamRubberStatus.FINISHED.value
        ]
        home_wins = sum(1 for r in finished if r["winner_entry_id"] == tie["entry_a_id"])
        away_wins = sum(1 for r in finished if r["winner_entry_id"] == tie["entry_b_id"])
        repo.set_team_tie_scores(conn, tie_id, home_wins, away_wins)

        if home_wins >= target_wins or away_wins >= target_wins:
            champion = tie["entry_a_id"] if home_wins >= target_wins else tie["entry_b_id"]
            repo.mark_team_tie_finished(conn, tie_id, champion)
            # 提前结束：未打的盘标记 SKIPPED（FINISHED 的盘不动）。
            repo.skip_open_team_rubbers(conn, tie_id)
    return _build_view(conn, repo.get_team_tie(conn, tie_id))
