"""个人赛赛制处理器。

Handler 只负责选择和编排既有服务。小组、排名与淘汰的业务算法仍分别留在
``groups``、``matches``、``rankings`` 与 ``knockout`` 中，避免出现第二套规则。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import sqlite3

from .. import repository as repo
from ..domain import ranking as ranking_domain
from ..models import (
    EventType,
    MatchBracket,
    MatchStage,
    MatchStatus,
    ResultType,
    TournamentStage,
)
from . import knockout as knockout_service
from . import matches as matches_service
from . import rankings as rankings_service


GROUP_KNOCKOUT = "GROUP_KNOCKOUT"
ROUND_ROBIN = "ROUND_ROBIN"
SINGLE_ELIMINATION = "SINGLE_ELIMINATION"


@dataclass(frozen=True)
class MatchGenerationResult:
    """赛制生成比赛后的通用结果；小组明细仅由需要分组的赛制提供。"""

    matches_generated: int
    per_group: dict[str, int] = field(default_factory=dict)


class FormatHandlerError(Exception):
    """赛制入口的可预期业务错误。"""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


class UnsupportedFormatError(FormatHandlerError):
    def __init__(self, format_code: str):
        super().__init__(f"不支持的个人赛赛制：{format_code}", 422)


def validate_rule_config(format_code: str, rule_config: object | None) -> dict:
    """校验 A 轨持久化前后的 Handler 专属配置。

    旧顶层赛事字段仍是既有规则的唯一来源；这里只接受新增的 ``draw_seed``，
    未知键和布尔值（Python 中 bool 是 int 的子类）均显式拒绝。
    """
    if format_code not in {GROUP_KNOCKOUT, ROUND_ROBIN, SINGLE_ELIMINATION}:
        raise UnsupportedFormatError(format_code)
    if rule_config is None:
        return {}
    if not isinstance(rule_config, dict):
        raise FormatHandlerError("rule_config 必须是对象", 422)
    allowed = {"draw_seed"} if format_code == SINGLE_ELIMINATION else set()
    unknown = set(rule_config) - allowed
    if unknown:
        raise FormatHandlerError(f"rule_config 包含未知配置：{', '.join(sorted(unknown))}", 422)
    if "draw_seed" in rule_config and (
        isinstance(rule_config["draw_seed"], bool) or not isinstance(rule_config["draw_seed"], int)
    ):
        raise FormatHandlerError("rule_config.draw_seed 必须是整数", 422)
    return dict(rule_config)


class FormatHandler(ABC):
    """D1B 冻结的个人赛赛制契约。"""

    format_code: str

    @abstractmethod
    def validate_config(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        """校验当前赛制的最小配置，返回赛事数据。"""

    @abstractmethod
    def generate_matches(
        self, conn: sqlite3.Connection, tournament_id: int
    ) -> MatchGenerationResult:
        """生成当前赛制的首阶段比赛。"""

    @abstractmethod
    def calculate_ranking(self, conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
        """返回当前赛制需要的排名。"""

    @abstractmethod
    def advance_participants(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        """把当前阶段的确定参赛者推进到下一阶段。"""

    @abstractmethod
    def handle_bye(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        """报告既有签表已处理的轮空；不把轮空伪造成正常比分。"""

    @abstractmethod
    def get_completion_state(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        """返回赛制的可推进与完成状态。"""


class GroupKnockoutHandler(FormatHandler):
    """把既有“小组赛 → 排名/出线 → 淘汰”主链接入统一契约。"""

    format_code = GROUP_KNOCKOUT

    def validate_config(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise FormatHandlerError("赛事不存在", 404)
        if tournament["event_type"] == EventType.TEAM.value:
            raise FormatHandlerError("团体赛不使用个人赛赛制处理器")
        if tournament["group_count"] < 1:
            raise FormatHandlerError("小组淘汰赛至少需要一个小组")
        if tournament["qualify_per_group"] < 1:
            raise FormatHandlerError("小组淘汰赛每组至少需要一个出线名额")
        validate_rule_config(self.format_code, tournament.get("rule_config"))
        return tournament

    def generate_matches(
        self, conn: sqlite3.Connection, tournament_id: int
    ) -> MatchGenerationResult:
        self.validate_config(conn, tournament_id)
        # 分组由既有 groups 服务负责；这里不改变其事务和阶段守卫。
        total, per_group = matches_service.generate_group_matches(conn, tournament_id)
        return MatchGenerationResult(matches_generated=total, per_group=per_group)

    def calculate_ranking(self, conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
        self.validate_config(conn, tournament_id)
        return rankings_service.get_rankings(conn, tournament_id)

    def advance_participants(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        # generate_knockout 已负责读取排名、校验出线及创建签表；不要复制该算法。
        # 其中的既有 WALKOVER 推进也在该服务内完成；handle_bye 只提供统一的
        # 观察入口，不能在此重复触发副作用。
        return knockout_service.generate_knockout(conn, tournament_id)

    def handle_bye(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        # 既有 knockout 服务在建签时完成 WALKOVER 自动晋级。此处只提供统一契约
        # 下的可观察结果，不再生成第二套 BYE 算法。
        walkovers = [
            match["id"]
            for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
            if match["bracket"] == MatchBracket.MAIN.value
            and match["status"] == MatchStatus.FINISHED.value
            and match.get("result_type") == ResultType.WALKOVER.value
        ]
        return {"handled_by": "existing_knockout_service", "walkover_match_ids": walkovers}

    def get_completion_state(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        tournament = self.validate_config(conn, tournament_id)
        stage = tournament["stage"]
        if stage == TournamentStage.FINISHED.value:
            return {"state": "COMPLETED", "can_advance": False, "completed": True}
        if stage == TournamentStage.KNOCKOUT.value:
            return {"state": "KNOCKOUT_IN_PROGRESS", "can_advance": False, "completed": False}
        if stage != TournamentStage.GROUP_STAGE.value:
            return {"state": "GROUP_MATCHES_NOT_GENERATED", "can_advance": False, "completed": False}

        # 与既有 generate_knockout 使用同一排名聚合结果，确保查询状态不会比
        # 真实推进更乐观。有效人工裁定会由默认 include_decisions=True 的排名
        # 服务消化，Handler 不复制裁定规则。
        rankings = rankings_service.get_rankings(conn, tournament_id)
        if any(group["finished_matches"] < group["total_matches"] for group in rankings):
            return {"state": "GROUP_STAGE_IN_PROGRESS", "can_advance": False, "completed": False}
        if any(group["ambiguous_qualification"] for group in rankings):
            return {"state": "QUALIFICATION_UNRESOLVED", "can_advance": False, "completed": False}

        # 只有与真实 generate_knockout 共用的无副作用前置检查成功时，才可以
        # 报告 READY；不能只凭排名完成度自行猜测签表一定可构造。
        try:
            knockout_service.prepare_knockout_generation(conn, tournament_id)
        except knockout_service.KnockoutError:
            return {"state": "KNOCKOUT_NOT_READY", "can_advance": False, "completed": False}
        return {"state": "KNOCKOUT_READY", "can_advance": True, "completed": False}


class RoundRobinHandler(FormatHandler):
    """无分组的全体单循环赛；不生成任何淘汰阶段。"""

    format_code = ROUND_ROBIN

    def validate_config(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise FormatHandlerError("赛事不存在", 404)
        if tournament["event_type"] == EventType.TEAM.value:
            raise FormatHandlerError("团体赛不使用个人赛赛制处理器")
        validate_rule_config(self.format_code, tournament.get("rule_config"))
        return tournament

    def generate_matches(self, conn: sqlite3.Connection, tournament_id: int) -> MatchGenerationResult:
        self.validate_config(conn, tournament_id)
        try:
            total = matches_service.generate_round_robin_matches(conn, tournament_id)
        except matches_service.MatchesExistError as exc:
            raise FormatHandlerError(str(exc)) from exc
        except matches_service.TournamentStageError as exc:
            raise FormatHandlerError(str(exc)) from exc
        return MatchGenerationResult(matches_generated=total)

    def calculate_ranking(self, conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
        self.validate_config(conn, tournament_id)
        # 已生成的成绩仍属于排名事实；退赛只影响后续参赛资格，不能让历史对阵
        # 在排名聚合中失去 stats 槽位。
        entries = repo.list_entries(conn, tournament_id)
        matches = repo.list_matches(conn, tournament_id, MatchStage.GROUP.value)
        rankings = ranking_domain.compute_group_rankings(
            [repo.decorate_match(conn, match) for match in matches], [entry["id"] for entry in entries]
        )
        names = {entry["id"]: entry["display_name"] for entry in entries}
        statuses = {entry["id"]: entry["status"] for entry in entries}
        return [
            {**row, "name": names[row["player_id"]], "entry_status": statuses[row["player_id"]]}
            for row in rankings
        ]

    def advance_participants(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        return {"advanced": False, "reason": "ROUND_ROBIN 没有下一淘汰阶段"}

    def handle_bye(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        return {"handled_by": "not_applicable", "walkover_match_ids": []}

    def get_completion_state(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        tournament = self.validate_config(conn, tournament_id)
        matches = repo.list_matches(conn, tournament_id, MatchStage.GROUP.value)
        if not matches or tournament["stage"] == TournamentStage.REGISTRATION.value:
            return {"state": "MATCHES_NOT_GENERATED", "can_advance": False, "completed": False}
        if any(match["status"] != MatchStatus.FINISHED.value for match in matches):
            return {"state": "ROUND_ROBIN_IN_PROGRESS", "can_advance": False, "completed": False}
        rankings = self.calculate_ranking(conn, tournament_id)
        if any(row["tied"] for row in rankings):
            decorated = [repo.decorate_match(conn, match) for match in matches]
            missing = ranking_domain.missing_point_score_match_ids(
                decorated, rankings, len(rankings), resolve_all_ties=True
            )
            if missing:
                return {"state": "RANKING_DATA_INSUFFICIENT", "can_advance": False, "completed": False}
            return {"state": "RANKING_UNRESOLVED", "can_advance": False, "completed": False}
        return {"state": "COMPLETED", "can_advance": False, "completed": True}


class SingleEliminationHandler(FormatHandler):
    """从 ACTIVE Entry 直接生成主签，复用淘汰服务的胜者传播。"""

    format_code = SINGLE_ELIMINATION

    def validate_config(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise FormatHandlerError("赛事不存在", 404)
        if tournament["event_type"] == EventType.TEAM.value:
            raise FormatHandlerError("团体赛不使用个人赛赛制处理器")
        validate_rule_config(self.format_code, tournament.get("rule_config"))
        return tournament

    def generate_matches(self, conn: sqlite3.Connection, tournament_id: int) -> MatchGenerationResult:
        tournament = self.validate_config(conn, tournament_id)
        config = validate_rule_config(self.format_code, tournament.get("rule_config"))
        try:
            tree = knockout_service.generate_single_elimination(
                conn, tournament_id, draw_seed=config.get("draw_seed")
            )
        except knockout_service.KnockoutError as exc:
            raise FormatHandlerError(str(exc), exc.code) from exc
        return MatchGenerationResult(matches_generated=sum(len(round_["matches"]) for round_ in tree["rounds"]))

    def calculate_ranking(self, conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
        self.validate_config(conn, tournament_id)
        # 淘汰赛的冠军/名次由 get_knockout 的 placement 结果负责，绝不伪造小组排名。
        return knockout_service.get_knockout(conn, tournament_id)["placements"]

    def advance_participants(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        return {"advanced": False, "reason": "胜者由既有淘汰链自动推进"}

    def handle_bye(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        walkovers = [
            match["id"] for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
            if match["bracket"] == MatchBracket.MAIN.value
            and match["status"] == MatchStatus.FINISHED.value
            and match.get("result_type") == ResultType.WALKOVER.value
        ]
        return {"handled_by": "existing_knockout_service", "walkover_match_ids": walkovers}

    def get_completion_state(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        tournament = self.validate_config(conn, tournament_id)
        if tournament["stage"] == TournamentStage.FINISHED.value:
            return {"state": "COMPLETED", "can_advance": False, "completed": True}
        if tournament["stage"] == TournamentStage.KNOCKOUT.value:
            return {"state": "KNOCKOUT_IN_PROGRESS", "can_advance": False, "completed": False}
        return {"state": "MATCHES_NOT_GENERATED", "can_advance": False, "completed": False}


_HANDLERS: dict[str, FormatHandler] = {
    GROUP_KNOCKOUT: GroupKnockoutHandler(),
    ROUND_ROBIN: RoundRobinHandler(),
    SINGLE_ELIMINATION: SingleEliminationHandler(),
}


def resolve_format_handler(format_code: str) -> FormatHandler:
    """集中解析已支持赛制；禁止把未知 code 静默回退到小组淘汰。"""
    try:
        return _HANDLERS[format_code]
    except KeyError as exc:
        raise UnsupportedFormatError(format_code) from exc


def sync_round_robin_stage(conn: sqlite3.Connection, tournament_id: int) -> None:
    """把已持久化循环赛的完成态同步到赛事生命周期，不负责提交事务。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None or tournament.get("format_code") != ROUND_ROBIN:
        return

    completion = resolve_format_handler(ROUND_ROBIN).get_completion_state(conn, tournament_id)
    if completion["state"] == "COMPLETED":
        if tournament["stage"] != TournamentStage.FINISHED.value:
            repo.update_tournament_stage(conn, tournament_id, TournamentStage.FINISHED.value)
    elif tournament["stage"] == TournamentStage.FINISHED.value:
        repo.update_tournament_stage(conn, tournament_id, TournamentStage.GROUP_STAGE.value)
