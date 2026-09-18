"""预计上场时间（A2 / ETA V1）：只读模拟，不写数据库。

复用 `scheduling.build_plan_state()` + `scheduling.plan_batch()`，因此与
`schedule-next`、dashboard 建议使用**同一套**排台规则
（硬约束 → 组台亲和 → 组间进度公平 → 连续上场软惩罚 → 稳定确定性排序），
不存在第二套 ETA 专用调度算法。

模拟方式：
  1. 以 T0 为基准；
  2. 正在进行的比赛按 剩余时间 = max(下限, 典型时长 - 已进行时间) 进入结束队列；
  3. 每轮先把到点的比赛标记结束（释放球台、更新组进度与"最近完成"），
     再让 planner 给空闲球台排下一批，记为在 T 开始、T + 典型时长结束；
  4. 记录每场 WAITING 比赛首次获得球台的时刻（estimated_start_at）与
     在此之前已经开始的其他比赛数量（queue_ahead）。

不做的事（宁可返回 null 也不编造）：
  - 不预测比赛胜负，因此签位未定的后续轮次不会被模拟到，其 ETA 为 null；
  - 不写任何业务数据（纯内存模拟，测试用数据库指纹校验）。
"""

import sqlite3
from datetime import datetime, timedelta

from .. import repository as repo
from . import match_timing
from . import scheduling

# 模拟批次上限（技术参数）：避免超大规模赛事把只读接口拖成长时间计算。
MAX_SIMULATED_BATCHES = 400

REASON_BRACKET_PENDING = "签位未定，无法估算"
REASON_NOT_REACHED = "模拟范围内未排上"


class ScheduleEstimateError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _playing_remaining_seconds(match: dict, now: datetime, typical: int) -> int:
    """进行中比赛的预计剩余时间：不让已打很久的比赛再占满一个完整周期。"""
    started = match_timing.parse_utc(match.get("started_at"))
    if started is None:
        # 旧数据/未记录开始时间：保守按完整典型时长处理（无法判断已进行多久）。
        return typical
    elapsed = (now - started).total_seconds()
    remaining = typical - elapsed
    if remaining > typical:
        # 开始时间在未来（时钟漂移）时按完整周期处理
        remaining = typical
    return int(max(match_timing.PLAYING_REMAINING_FLOOR_SECONDS, remaining))


def estimate_schedule(
    conn: sqlite3.Connection,
    tournament_id: int,
    *,
    now: str | None = None,
) -> dict:
    """返回赛事内每场 WAITING 比赛的预计上场时间（只读，不修改数据库）。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise ScheduleEstimateError("赛事不存在", 404)
    typical = match_timing.typical_duration_seconds(conn, tournament_id)
    duration = typical["seconds"]
    now_dt = match_timing.parse_utc(now) if now else match_timing.parse_utc(repo.utc_now(conn))
    if now_dt is None:
        raise ScheduleEstimateError("时间参数非法", 422)

    state = scheduling.build_plan_state(conn, tournament_id)
    match_by_id = {match["id"]: match for match in state["matches"]}
    targets = [
        match["id"] for match in state["matches"]
        if match["status"] == "WAITING"
    ]
    initial_playing = sum(1 for match in state["matches"] if match["status"] == "PLAYING")

    # 模拟中的时间线：已经开始过的比赛时刻（用于 queue_ahead），以及预计结束时刻。
    started_times: list[datetime] = []
    finish_at: dict[int, datetime] = {}
    for match in state["matches"]:
        if match["status"] != "PLAYING":
            continue
        started = match_timing.parse_utc(match.get("started_at"))
        started_times.append(started or now_dt)
        finish_at[match["id"]] = now_dt + timedelta(
            seconds=_playing_remaining_seconds(match, now_dt, duration)
        )

    start_at: dict[int, datetime] = {}
    queue_ahead: dict[int, int] = {}
    cursor = now_dt
    batches = 0
    truncated = False
    for _ in range(MAX_SIMULATED_BATCHES):
        for match_id in [mid for mid, moment in finish_at.items() if moment <= cursor]:
            scheduling.finish_match_in_state(state, match_id)
            finish_at.pop(match_id, None)
        assignments = scheduling.plan_batch(state)
        if not assignments:
            if finish_at:
                # 还有比赛在打：时间推进到最早结束的时刻，再试一次
                cursor = min(finish_at.values())
                continue
            break
        batches += 1
        queue_position = sum(1 for moment in started_times if moment < cursor)
        for match_id, _table_id in assignments:
            start_at[match_id] = cursor
            queue_ahead[match_id] = queue_position
            started_times.append(cursor)
            finish_at[match_id] = cursor + timedelta(seconds=duration)
    else:
        truncated = True

    rows = []
    for match_id in targets:
        match = match_by_id[match_id]
        moment = start_at.get(match_id)
        if moment is None:
            ready = scheduling.match_ready(match)
            rows.append(
                {
                    "match_id": match_id,
                    "stage": match["stage"],
                    "round": match["round"],
                    "group_id": match["group_id"],
                    "estimated_start_at": None,
                    "estimated_wait_minutes": None,
                    "queue_ahead": None,
                    "estimate_basis": None,
                    "unavailable_reason": REASON_NOT_REACHED if ready else REASON_BRACKET_PENDING,
                }
            )
            continue
        rows.append(
            {
                "match_id": match_id,
                "stage": match["stage"],
                "round": match["round"],
                "group_id": match["group_id"],
                "estimated_start_at": match_timing.format_utc(moment),
                "estimated_wait_minutes": round((moment - now_dt).total_seconds() / 60, 1),
                "queue_ahead": queue_ahead.get(match_id, 0),
                "estimate_basis": typical["basis"],
                "unavailable_reason": None,
            }
        )
    rows.sort(
        key=lambda row: (
            row["estimated_start_at"] is None,
            row["estimated_start_at"] or "",
            row["match_id"],
        )
    )
    return {
        "tournament_id": tournament_id,
        "generated_at": match_timing.format_utc(now_dt),
        "estimated_match_duration_seconds": duration,
        "estimate_basis": typical["basis"],
        "sample_count": typical["sample_count"],
        "initial_playing_matches": initial_playing,
        "simulated_batches": batches,
        "truncated": truncated,
        "matches": rows,
    }
