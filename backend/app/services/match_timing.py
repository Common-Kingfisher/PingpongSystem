"""比赛时间基础：真实耗时样本与赛事典型耗时（A2）。

时间约定（与全库一致）：UTC SQLite 时间戳，格式 'YYYY-MM-DD HH:MM:SS'
（由 repository 的 mark_match_* / utc_now 统一写入，等价于 datetime('now')）。
本模块只做只读推导，不写数据库，也不存 duration 字段（实时相减即可）。

统计口径（重要）：
  - 只有"真实打完"的比赛才进入耗时样本：started_at 与 finished_at 都存在、
    结果类型为 NORMAL、且 finished_at >= started_at；
  - 排除系统轮空（started_at 为空）、WAITING 直接录分（started_at 为空）、
    以及 FORFEIT / WALKOVER / NO_SHOW / DISQUALIFIED 等异常结果；
  - 赛事典型耗时优先取中位数（median），避免个别超长比赛或忘记录分把均值拖偏。
"""

import sqlite3
import statistics
from datetime import datetime, timezone

from .. import repository as repo

# 冷启动技术估算参数（产品估算值，不是 ITTF 官方时长；集中定义，未来可由赛事配置覆盖）。
DEFAULT_DURATION_SECONDS_BY_GAMES_TO_WIN: dict[int, int] = {
    1: 8 * 60,
    2: 15 * 60,
    3: 20 * 60,
    4: 30 * 60,
}
DEFAULT_MATCH_DURATION_SECONDS = 15 * 60
# 每局目标分基准：11 分制为 1.0，其它分制按比例线性缩放（例如 21 分制约 ×1.9）。
REFERENCE_POINTS_TO_WIN = 11

# 少于该样本数时使用冷启动默认值（样本太少时中位数不稳定）。
MIN_LIVE_SAMPLES = 3

# 进行中比赛的剩余时间下限（技术值，避免"已经超时"的比赛被估成负数）。
PLAYING_REMAINING_FLOOR_SECONDS = 60

ESTIMATE_BASIS_LIVE = "LIVE_MEDIAN"
ESTIMATE_BASIS_FORMAT = "FORMAT_DEFAULT"


def parse_utc(value: str | None) -> datetime | None:
    """解析库内时间戳为带时区的 UTC datetime（兼容 ISO 'Z' 形式与旧数据）。"""
    if not value:
        return None
    text = value.strip().replace(" ", "T", 1)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_utc(moment: datetime) -> str:
    """按库内约定格式化（UTC SQLite 时间戳，秒精度）。"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def format_default_duration_seconds(games_to_win: int, points_to_win: int) -> int:
    """按赛制给出冷启动技术估算时长（产品估算值，非官方时长）。"""
    base = DEFAULT_DURATION_SECONDS_BY_GAMES_TO_WIN.get(
        games_to_win, DEFAULT_MATCH_DURATION_SECONDS
    )
    points = max(1, points_to_win or REFERENCE_POINTS_TO_WIN)
    return int(round(base * points / REFERENCE_POINTS_TO_WIN))


def real_match_duration_seconds(match: dict) -> int | None:
    """一场比赛的真实耗时秒数；不满足"真实打完"条件时返回 None。

    排除：系统轮空 / WAITING 直接录分（started_at 为空）、异常结果、
    以及时间倒挂或零时长的数据。
    """
    if (match.get("result_type") or "NORMAL") != "NORMAL":
        return None
    started = parse_utc(match.get("started_at"))
    finished = parse_utc(match.get("finished_at"))
    if started is None or finished is None:
        return None
    seconds = int((finished - started).total_seconds())
    return seconds if seconds > 0 else None


def list_duration_samples(conn: sqlite3.Connection, tournament_id: int) -> list[int]:
    """赛事内全部有效真实耗时样本（秒），按比赛 id 升序，便于测试与复核。"""
    samples: list[int] = []
    for match in repo.list_matches(conn, tournament_id):
        seconds = real_match_duration_seconds(match)
        if seconds is not None:
            samples.append(seconds)
    return samples


def typical_duration_seconds(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """赛事典型单场耗时：样本充足用真实中位数，否则用赛制冷启动估算。

    返回 {seconds, basis, sample_count}；basis 取值 LIVE_MEDIAN 或 FORMAT_DEFAULT。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise ValueError("赛事不存在")
    samples = list_duration_samples(conn, tournament_id)
    if len(samples) >= MIN_LIVE_SAMPLES:
        return {
            "seconds": int(round(statistics.median(samples))),
            "basis": ESTIMATE_BASIS_LIVE,
            "sample_count": len(samples),
        }
    return {
        "seconds": format_default_duration_seconds(
            tournament["games_to_win"], tournament["points_to_win"]
        ),
        "basis": ESTIMATE_BASIS_FORMAT,
        "sample_count": len(samples),
    }
