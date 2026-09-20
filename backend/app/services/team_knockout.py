"""团体淘汰签服务（A6.4）：按**已确认的晋级队伍**生成团体淘汰签。

规则源：[`docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md`](../../../docs/TEAM_QUALIFICATION_KNOCKOUT_V1.md)；
配对与轮次结构在 `domain/team_knockout.py`（纯函数）。

## 复用什么 / 不复用什么

- **复用** `team_ties`（`stage='KNOCKOUT'`）：团体淘汰赛的最小比赛单位仍然是 TeamTie，
  因此**不新建** `team_knockout_ties`，也不允许出现第二套对抗系统。
  `team_ties.group_id` 在 KNOCKOUT 段恒为 NULL（与 `create_team_tie` 的既有 guard 一致）。
- **复用** `LOCAL_CLASSIC_5_V1`：淘汰赛的盘骨架仍由既有
  `services/team_ties.py::build_rubber_skeleton` 按需创建，本服务**不**自动建盘
  （批量初始化赛制是另一个业务动作，且建盘有自己的事务契约）。
- **不复用**个人赛淘汰逻辑：不创建任何 `matches` 行、不调用个人赛 `services/knockout.py`、
  不使用个人赛的配对/名次规则。

## 生成来源

只使用 **A6.3 已确认**的晋级队伍（`team_qualifications`）。若尚未确认，或晋级队伍
不能组成合法签表（数量/分组不符合 V1 范围），一律拒绝，绝不猜测晋级者。

## 本版本建立到哪一层（重要）

生成时只写入**可以立刻进行的首轮对抗**（双方都已确认）：8 支队伍即 4 场
Quarter Final。后续轮次（Semi Final / Final）在**读取时**按签表几何补全为
"待定槽位"（`rounds[i].matches` 为空、`match_count` 给出应有场次数），
因此消费方能直接渲染完整签表；等上游胜者产生后再建立对应 TeamTie。

**为什么不预建空对抗**：`team_ties.entry_a_id / entry_b_id` 是 `NOT NULL`，
且该表没有 `prev` 依赖列（个人赛 `matches` 两者都有）。只放开 NULL 而不加依赖列
仍然无法把胜者推进到下一轮，只会留下一批没有含义、也无法消费的空行。
因此本版本**不伪造**空槽位对抗；"允许待定槽位 + 上游依赖"（需要 `team_ties`
表迁移）作为后续独立批次处理，见 `docs/TEAM_DOMAIN.md`。

## 并发

"查已有 KNOCKOUT 对抗 → 生成一批对抗"是 read-check-write，
因此使用 `services/transaction.py::write_transaction`（`BEGIN IMMEDIATE`）：
写锁内重新检查已有对抗，因此两个并发生成请求只会一个成功，另一个得到可读 409。
"""

import sqlite3

from .. import repository as repo
from ..domain import team_knockout as domain
from ..domain.team_knockout import TeamKnockoutError
from ..models import EventType, MatchStage
from . import team_qualification as qualification_service
from . import team_standings as standings_service
from .teams import ENTRY_STATUS_WITHDRAWN
from .transaction import TransactionBusyError, write_transaction

ServiceError = TeamKnockoutError

KNOCKOUT_STAGE = MatchStage.KNOCKOUT.value


def _tournament(conn: sqlite3.Connection, tournament_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise ServiceError("赛事不存在", 404)
    if tournament["event_type"] != EventType.TEAM.value:
        raise ServiceError(
            f"当前赛事项目是 {tournament['event_type']}，只有团体赛（TEAM）有团体淘汰赛", 409
        )
    return tournament


def _seed_order_for_group(group_view: dict, confirmed_ids: set[int]) -> list[int]:
    """把一个小组的**已确认晋级队伍**按唯一名次排成 `[第1名, 第2名, ...]`。

    `group_view` 是 A6.2 的小组排名结果（至少含 `group_name` / `qualify_count` /
    `standings`）。纯函数、不访问数据库，便于直接测试判据。

    判据建立在**可晋级候选**上，而不是只看已确认队伍：

    - 一支队伍占据 `[rank_start, rank_end]` 内的**每个**位置；
    - 第 k 个位置必须**恰好有一支可晋级候选**，否则"第 k 名是谁"没有唯一确定
      → 抛 409（本版本不支持人工指定淘汰种子顺序）；
    - 名次唯一后，该位置上的队伍还必须就是被确认晋级的那一支，否则 409。

    绝不使用展示顺序、提交顺序或 entry id 作为兜底。
    """
    expected = group_view["qualify_count"]
    standings = group_view["standings"]
    eligible = [
        row["team_entry_id"]
        for row in standings
        if row["eligible_for_qualification"] and row["status"] != ENTRY_STATUS_WITHDRAWN
    ]
    rank_of_team = {
        row["team_entry_id"]: (row["rank_start"], row["rank_end"]) for row in standings
    }

    team_at_rank: dict[int, int] = {}
    ambiguous_ranks: list[int] = []
    for rank in range(1, expected + 1):
        owners = [
            team_id for team_id in eligible
            if rank_of_team[team_id][0] <= rank <= rank_of_team[team_id][1]
        ]
        if len(owners) == 1:
            team_at_rank[rank] = owners[0]
        else:
            ambiguous_ranks.append(rank)

    if ambiguous_ranks:
        names = "、".join(f"第 {rank} 名" for rank in ambiguous_ranks)
        raise ServiceError(
            f"{group_view['group_name']}的晋级队伍已经确认，但组内种子顺序仍存在并列，"
            f"无法唯一确定{names}；当前版本不支持人工指定淘汰种子顺序",
            409,
        )

    unconfirmed = [
        rank for rank, team_id in team_at_rank.items() if team_id not in confirmed_ids
    ]
    if unconfirmed:
        names = "、".join(f"第 {rank} 名" for rank in sorted(unconfirmed))
        raise ServiceError(
            f"{group_view['group_name']} 的{names}（名次唯一）不在已确认的晋级名单中，"
            f"不能生成团体淘汰签；请先重新确认晋级名单",
            409,
        )
    return [team_at_rank[rank] for rank in range(1, expected + 1)]


def _qualified_by_group(
    conn: sqlite3.Connection, tournament_id: int
) -> list[list[int]]:
    """已确认的晋级队伍，按小组顺序、**组内唯一名次**排列（不是展示顺序）。

    ## 为什么必须重新读 A6.2 的排名，而不是用确认结果的展示顺序

    确认结果（`team_qualifications`）的展示顺序是"小组顺序 → 组内排名展示序号 → entry id"，
    而 A6.2 明确规定**并列区间内的展示顺序不代表名次**。若直接照抄展示顺序，
    就等于用展示顺序 / 数据库 id 静默打破了并列 —— 违反
    `TEAM_GROUP_RULES_V1` / `TEAM_QUALIFICATION_KNOCKOUT_V1` 的"禁止按 id / 展示顺序破并列"。

    因此这里重新读取 standings，按**名次位置**（`rank_start <= k <= rank_end`）判断第 k 名是否唯一：
    只有第 k 名恰好由**一支可晋级候选**占位、且这支就是被确认晋级的那一支时，
    才认为该名次已唯一确定。`qualify_count` 为 2 时即要求第 1 名与第 2 名各自唯一；
    判据由 `_seed_order_for_group` 实现（纯函数，便于直接测试）。

    ## 只有"谁晋级"由确认决定

    确认只回答"哪些队伍晋级"，**不**决定并列晋级队伍之间谁是第 1 种子、谁是第 2 种子。
    若确认后名次仍不唯一 → 409，且**不创建任何淘汰对抗**。
    本版本**不支持**人工指定淘汰种子顺序（没有 manual seed ordering 接口）。
    """
    tournament = _tournament(conn, tournament_id)
    confirmed = qualification_service.get_qualification(conn, tournament_id)["confirmed"]
    if not confirmed:
        raise ServiceError("尚未确认团体晋级名单，请先确认晋级后再生成淘汰签", 409)

    groups = repo.list_groups(conn, tournament_id)
    if not groups:
        raise ServiceError("赛事还没有小组，不能生成团体淘汰签", 409)

    confirmed_ids = {row["team_entry_id"] for row in confirmed}
    by_group: dict[int, list[int]] = {}
    for row in confirmed:
        if row["group_id"] is None:
            raise ServiceError("已确认的晋级队伍缺少所属小组，无法生成淘汰签", 409)
        by_group.setdefault(row["group_id"], []).append(row["team_entry_id"])

    ordered: list[list[int]] = []
    for group in groups:
        expected = group["qualify_count"] or tournament["qualify_per_group"]
        picked = by_group.get(group["id"], [])
        if len(picked) != expected:
            raise ServiceError(
                f"{group['name']} 已确认 {len(picked)} 支晋级队伍，与晋级名额 {expected} 不一致，"
                f"不能生成团体淘汰签",
                409,
            )

        # 判断"第 k 名是否唯一"并把已确认队伍按名次排好（判据见 `_seed_order_for_group`）。
        # 这里必须重新读 A6.2 的排名：确认结果的展示顺序**不代表名次**，
        # 直接照抄等于用展示顺序 / entry id 静默打破并列。
        group_view = standings_service.get_team_group_standings(
            conn, tournament_id, group["id"]
        )
        ordered.append(_seed_order_for_group(group_view, confirmed_ids))

    # 已退赛的队伍不能被安排**新的**对抗（与 create_team_tie 的退赛口径一致）。
    # 退赛不会改变已完成的排名事实，因此确认名单可能仍然"数量正确"——
    # 必须在生成前显式拦下，否则会造出一个含已退赛队伍的签表。
    status_by_team = {
        entry["id"]: entry["status"]
        for entry in repo.list_entries_by_type(conn, tournament_id, EventType.TEAM.value)
    }
    all_confirmed = [team_id for group in ordered for team_id in group]
    withdrawn = [
        team_id for team_id in all_confirmed
        if status_by_team.get(team_id) == ENTRY_STATUS_WITHDRAWN
    ]
    if withdrawn:
        raise ServiceError(
            f"已确认的晋级队伍中有 {len(withdrawn)} 支已经退赛，不能生成团体淘汰签；"
            f"请先重新确认晋级名单",
            409,
        )

    return ordered


def _team_view(names: dict[int, str], entry_id: int | None) -> dict | None:
    if entry_id is None:
        return None
    return {"team_entry_id": entry_id, "team_name": names.get(entry_id, str(entry_id))}


def _stored_knockout_ties(conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
    """已入库的淘汰对抗（按 轮次 → 场序 → id 稳定排序）。"""
    ties = [
        tie
        for tie in repo.list_team_ties(conn, tournament_id)
        if tie["stage"] == KNOCKOUT_STAGE
    ]
    ties.sort(key=lambda tie: (tie["round"], tie["match_index"] or 0, tie["id"]))
    return ties


def _total_rounds(
    conn: sqlite3.Connection, tournament_id: int, stored: list[dict]
) -> int:
    """本次签表的总轮数（用于轮次展示名）。

    优先由已确认的晋级规模推导（2 的幂），规模不可得时退回"已入库轮次的最大值"。
    """
    try:
        total = sum(len(group) for group in _qualified_by_group(conn, tournament_id))
        rounds = domain.expected_round_count(total)
    except ServiceError:
        rounds = 0
    return max(rounds, max((tie["round"] for tie in stored), default=0), 1)


def _tie_view(tie: dict, names: dict[int, str], total_rounds: int) -> dict:
    a, b = tie["entry_a_id"], tie["entry_b_id"]
    return {
        "tie_id": tie["id"],
        "round": tie["round"],
        "round_name": domain.round_display_name(tie["round"], total_rounds),
        "match_index": tie["match_index"],
        # 双方已就位（首轮必然为真）；后续轮次在读取时补全为待定槽位。
        "teams_decided": a is not None and b is not None,
        "team_a": _team_view(names, a),
        "team_b": _team_view(names, b),
        "status": tie["status"],
        "team_a_score": tie["team_a_score"],
        "team_b_score": tie["team_b_score"],
        "winner_entry_id": tie["winner_entry_id"],
    }


def _planned_rounds(stored: list[dict], total_rounds: int) -> list[dict]:
    """完整签表的轮次骨架：已入库轮次用真实场次数，其余按几何推导为待定轮次。"""
    stored_counts: dict[int, int] = {}
    for tie in stored:
        stored_counts[tie["round"]] = stored_counts.get(tie["round"], 0) + 1

    rounds: list[dict] = []
    for round_no in range(1, total_rounds + 1):
        count = stored_counts.get(round_no)
        if count is None:
            count = max(1, 2 ** (total_rounds - round_no))
        rounds.append(
            {
                "round": round_no,
                "round_name": domain.round_display_name(round_no, total_rounds),
                "match_count": count,
            }
        )
    return rounds


def get_team_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """查询团体淘汰签（只读；未生成时返回空签表）。

    `rounds` 是**完整签表骨架**（含尚未产生参赛者的后续轮次，`matches` 为空），
    因此消费方可以直接渲染"QF → SF → Final"的整张表；
    `ties` 只包含**已建立**的对抗（本版本为首轮）。
    """
    _tournament(conn, tournament_id)
    stored = _stored_knockout_ties(conn, tournament_id)
    if not stored:
        return {
            "tournament_id": tournament_id,
            "generated": False,
            "rounds": [],
            "ties": [],
        }

    names = {
        entry["id"]: entry["display_name"]
        for entry in repo.list_entries_by_type(conn, tournament_id, EventType.TEAM.value)
    }
    total_rounds = _total_rounds(conn, tournament_id, stored)
    tie_views = [_tie_view(tie, names, total_rounds) for tie in stored]

    rounds: list[dict] = []
    for planned in _planned_rounds(stored, total_rounds):
        round_no = planned["round"]
        rounds.append(
            {
                "round": round_no,
                "round_name": planned["round_name"],
                "match_count": planned["match_count"],
                "matches": [tie for tie in tie_views if tie["round"] == round_no],
            }
        )

    return {
        "tournament_id": tournament_id,
        "generated": True,
        "rounds": rounds,
        "ties": tie_views,
    }


def generate_team_knockout(conn: sqlite3.Connection, tournament_id: int) -> dict:
    """按已确认的晋级名单生成团体淘汰签（全成或全不成）。

    只写入**可以立刻进行的首轮对抗**（双方都已确认）；后续轮次的对阵在读取时按签表
    几何补全为"待定槽位"，等上游胜者产生后再建立对应 TeamTie。

    为什么不分轮预建空对抗：`team_ties.entry_a_id / entry_b_id` 是 `NOT NULL`，
    且该表没有 `prev` 依赖列（个人赛 `matches` 两者都有）。若只放开 NULL 而不加依赖列，
    仍然无法把胜者推进到下一轮，只会留下一批**没有含义也无法消费**的空行。
    因此本版本**不伪造**空槽位对抗；把"允许待定槽位 + 上游依赖"作为后续独立批次
    （需要 `team_ties` 表迁移）处理，见 `docs/TEAM_DOMAIN.md`。

    守卫（顺序）：
    1. 赛事存在且是 TEAM 项目（404 / 409）；
    2. 已经有 `stage='KNOCKOUT'` 的对抗 → 409，**不**补齐、**不**覆盖、**不**重新生成；
    3. 尚未确认晋级 → 409（绝不猜测晋级者）；
    4. 晋级队伍无法组成合法签表 → 409（数量不一致 / 非 2 的幂 / 重复等）。
    """
    _tournament(conn, tournament_id)

    try:
        with write_transaction(
            conn,
            busy_message="团体淘汰签正在被另一个请求生成，请稍后重试",
            conflict_message="生成团体淘汰签时写入冲突，请稍后重试",
        ):
            # 写锁内重新读取：这里的判断才是可以安全写入的依据。
            _tournament(conn, tournament_id)
            existing = repo.count_team_ties(conn, tournament_id, stage=KNOCKOUT_STAGE)
            if existing:
                raise ServiceError(
                    f"团体淘汰签已经生成（现有 {existing} 场淘汰对抗），不能重复生成；"
                    f"本版本不支持补齐、覆盖或重新生成",
                    409,
                )

            qualifiers_by_group = _qualified_by_group(conn, tournament_id)
            # 首轮对阵来自域层（相邻组交叉）；后续轮次的场次由轮次几何推导。
            first_round = domain.build_first_round_pairs(qualifiers_by_group)
            # match_index 与 A6.1（Team Group Tie Generator）保持一致：**从 1 开始**。
            # 这里直接调用 repository 会绕过 service 的 `match_index >= 1` 守卫，
            # 因此 start=1 必须显式写出来，否则同一张 team_ties 会出现两套场序语义。
            for match_index, (team_a_id, team_b_id) in enumerate(first_round, start=1):
                repo.create_team_tie(
                    conn,
                    tournament_id,
                    KNOCKOUT_STAGE,
                    None,  # 淘汰赛段不挂小组（与既有 guard 一致）
                    1,     # 首轮
                    match_index,
                    team_a_id,
                    team_b_id,
                )
    except TransactionBusyError as exc:
        raise ServiceError(str(exc), exc.code) from None

    # 刻意不修改 `tournaments.stage`：TEAM 的阶段推进规则尚未冻结（见 docs/TEAM_DOMAIN.md）。
    return get_team_knockout(conn, tournament_id)
