"""比赛生成服务：小组循环赛生成。

## 事务边界（PR #68 review Finding #1）

生成是典型的"读 → 判断 → 写"：读赛事与分组、判断阶段与是否已生成、再写入比赛并推进阶段。
SQLite 下这**不是**原子操作（FastAPI 每个请求一条独立连接），因此两个并发请求可以同时
通过校验并双写。本模块因此把所有生成实现拆成两层：

```text
_generate_*_locked()   只做 校验 → 生成 → 推进阶段；不 begin / 不 commit / 不 rollback
generate_*()           自己拥有事务边界：write_transaction(BEGIN IMMEDIATE) 包住 locked 实现
```

**locked 实现绝不 `conn.commit()`**：一旦内层提前提交，外层写锁会在 invariant → generation
→ stage update 走完之前被释放，修复即失效。统一入口
（`formats.generate_matches_for_tournament`）已经持有写事务时，本模块的 public wrapper 走
`write_transaction` 的 SAVEPOINT 分支，因此仍然不会提前提交。
"""

import random
import sqlite3

from .. import repository as repo
from ..domain import round_robin
from ..models import EventType, MatchStage, MatchStatus, TournamentStage
from . import scores as scores_service
from .transaction import write_transaction

#: 生成入口拿不到写锁时的用户可读文案（由调用方映射成业务 409）。
GENERATION_BUSY_MESSAGE = "比赛生成正在由其他请求处理，请稍后重试"


class TournamentNotFoundError(Exception):
    pass


class TournamentStageError(Exception):
    pass


class NoGroupsError(Exception):
    pass


class MatchesExistError(Exception):
    pass


def _generate_group_matches_locked(
    conn: sqlite3.Connection, tournament_id: int
) -> tuple[int, dict[str, int]]:
    """为所有小组生成单循环比赛（**不含事务边界**）。

    调用方必须已经持有写事务。守卫：赛事必须存在、处于 REGISTRATION 阶段、
    已分组、且尚未生成过小组赛。
    团体赛（TEAM）不走这条路径：一场对抗是 TeamTie + 多盘 TeamRubber，
    不能展开成"Entry vs Entry"的普通比赛（见 services/team_ties.py 的说明）。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TournamentNotFoundError("赛事不存在")
    if tournament["event_type"] == EventType.TEAM.value:
        raise TournamentStageError("团体赛不生成小组循环赛：请使用团体对抗（TeamTie）接口")
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise TournamentStageError("当前阶段不允许生成小组比赛")
    groups = repo.list_groups(conn, tournament_id)
    if not groups:
        raise NoGroupsError("请先完成自动分组，再生成小组比赛")
    if repo.count_matches(conn, tournament_id, stage=MatchStage.GROUP.value) > 0:
        raise MatchesExistError("小组比赛已生成，不能重复生成")

    entries = [
        entry for entry in repo.list_entries(conn, tournament_id)
        if entry["status"] == "ACTIVE"
    ]
    by_group: dict[int, list[int]] = {}
    for entry in entries:
        if entry["group_id"] is not None:
            by_group.setdefault(entry["group_id"], []).append(entry["id"])
    entry_by_id = {e["id"]: e for e in entries}

    total = 0
    per_group: dict[str, int] = {}
    for group in groups:
        member_ids = by_group.get(group["id"], [])
        schedule = round_robin.round_robin(member_ids)
        per_group[group["name"]] = len(schedule)
        for round_num, a, b in schedule:
            ea, eb = entry_by_id[a], entry_by_id[b]
            player_a = ea["members"][0]["player_id"] if ea["entry_type"] == "SINGLES" else None
            player_b = eb["members"][0]["player_id"] if eb["entry_type"] == "SINGLES" else None
            repo.create_match(
                conn,
                tournament_id,
                MatchStage.GROUP.value,
                group["id"],
                round_num,
                None,
                player_a,
                player_b,
                entry_a_id=a,
                entry_b_id=b,
                bracket="GROUP",
            )
        total += len(schedule)

    repo.update_tournament_stage(conn, tournament_id, TournamentStage.GROUP_STAGE.value)
    return total, per_group


def generate_group_matches(
    conn: sqlite3.Connection, tournament_id: int
) -> tuple[int, dict[str, int]]:
    """为所有小组生成单循环比赛（同一写事务），赛事进入 GROUP_STAGE。

    返回 (总场数, {组名: 场数})。本函数自己拥有事务边界；并发生成时后来者会拿到
    前一个请求**已提交**的状态，因此既有的"已生成，不能重复生成"守卫一定命中。
    """
    with write_transaction(conn, busy_message=GENERATION_BUSY_MESSAGE):
        return _generate_group_matches_locked(conn, tournament_id)


def _generate_round_robin_matches_locked(
    conn: sqlite3.Connection, tournament_id: int
) -> int:
    """为未分组的个人循环赛生成全部对阵（**不含事务边界**）。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TournamentNotFoundError("赛事不存在")
    if tournament["event_type"] == EventType.TEAM.value:
        raise TournamentStageError("团体赛不生成个人循环赛")
    if repo.count_matches(conn, tournament_id, stage=MatchStage.GROUP.value):
        raise MatchesExistError("循环赛已生成，不能重复生成")
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        raise TournamentStageError("当前阶段不允许生成循环赛")
    entries = [
        entry for entry in repo.list_entries(conn, tournament_id)
        if entry["status"] == "ACTIVE"
    ]
    if len(entries) < 2:
        raise TournamentStageError("循环赛至少需要 2 名有效参赛位")
    by_id = {entry["id"]: entry for entry in entries}
    schedule = round_robin.round_robin(list(by_id))
    for round_num, entry_a_id, entry_b_id in schedule:
        entry_a, entry_b = by_id[entry_a_id], by_id[entry_b_id]
        repo.create_match(
            conn, tournament_id, MatchStage.GROUP.value, None, round_num, None,
            entry_a["members"][0]["player_id"] if entry_a["entry_type"] == "SINGLES" else None,
            entry_b["members"][0]["player_id"] if entry_b["entry_type"] == "SINGLES" else None,
            entry_a_id=entry_a_id, entry_b_id=entry_b_id, bracket="GROUP",
        )
    repo.update_tournament_stage(conn, tournament_id, TournamentStage.GROUP_STAGE.value)
    return len(schedule)


def generate_round_robin_matches(conn: sqlite3.Connection, tournament_id: int) -> int:
    """为未分组的个人循环赛生成全部对阵（同一写事务），并复用既有 round_robin 算法。"""
    with write_transaction(conn, busy_message=GENERATION_BUSY_MESSAGE):
        return _generate_round_robin_matches_locked(conn, tournament_id)


def demo_score_options(games_to_win: int) -> list[tuple[int, int]]:
    """按赛事局制生成合法的模拟大比分：N:0 … N:(N-1) 以及反向。

    三局两胜（N=2）→ 2:0/2:1/0:2/1:2；五局三胜（N=3）→ 3:0/3:1/3:2/…；
    七局四胜（N=4）→ 4:0…4:3/…。这样 demo 模拟不会产生被比分校验拒绝的结果。
    """
    games = max(1, games_to_win)
    return [(games, loser) for loser in range(games)] + [
        (loser, games) for loser in range(games)
    ]


def finish_group_stage(
    conn: sqlite3.Connection, tournament_id: int, rng: random.Random | None = None
) -> int:
    """Demo：模拟完成所有未结束的小组赛（复用真实 record_score 逻辑，随机非平局比分）。

    返回本次模拟结束的场数。仅 GROUP_STAGE 阶段可用。
    """
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise TournamentNotFoundError("赛事不存在")
    if tournament["event_type"] == EventType.TEAM.value:
        raise TournamentStageError("团体赛没有单打式小组赛，暂不支持模拟推进")
    if tournament["stage"] != TournamentStage.GROUP_STAGE.value:
        raise TournamentStageError("仅小组赛阶段可模拟完成剩余小组赛")

    matches = repo.list_matches(conn, tournament_id, stage=MatchStage.GROUP.value)
    unfinished = [m for m in matches if m["status"] != MatchStatus.FINISHED.value]
    rng = rng or random.Random()
    options = demo_score_options(tournament["games_to_win"])
    for m in unfinished:
        sa, sb = rng.choice(options)
        scores_service.record_score(conn, m["id"], sa, sb)
    return len(unfinished)
