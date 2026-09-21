"""个人赛赛制处理器。

Handler 只负责选择和编排既有服务。小组、排名与淘汰的业务算法仍分别留在
``groups``、``matches``、``rankings`` 与 ``knockout`` 中，避免出现第二套规则。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import sqlite3

from .. import repository as repo
from ..models import EventType, MatchBracket, MatchStage, MatchStatus, TournamentStage
from . import knockout as knockout_service
from . import matches as matches_service
from . import rankings as rankings_service


GROUP_KNOCKOUT = "GROUP_KNOCKOUT"


class FormatHandlerError(Exception):
    """赛制入口的可预期业务错误。"""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


class UnsupportedFormatError(FormatHandlerError):
    def __init__(self, format_code: str):
        super().__init__(f"不支持的个人赛赛制：{format_code}", 422)


class FormatHandler(ABC):
    """D1B 冻结的个人赛赛制契约。"""

    format_code: str

    @abstractmethod
    def validate_config(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        """校验当前赛制的最小配置，返回赛事数据。"""

    @abstractmethod
    def generate_matches(
        self, conn: sqlite3.Connection, tournament_id: int
    ) -> tuple[int, dict[str, int]]:
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
        return tournament

    def generate_matches(
        self, conn: sqlite3.Connection, tournament_id: int
    ) -> tuple[int, dict[str, int]]:
        self.validate_config(conn, tournament_id)
        # 分组由既有 groups 服务负责；这里不改变其事务和阶段守卫。
        return matches_service.generate_group_matches(conn, tournament_id)

    def calculate_ranking(self, conn: sqlite3.Connection, tournament_id: int) -> list[dict]:
        self.validate_config(conn, tournament_id)
        return rankings_service.get_rankings(conn, tournament_id)

    def advance_participants(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        # generate_knockout 已负责读取排名、校验出线及创建签表；不要复制该算法。
        tree = knockout_service.generate_knockout(conn, tournament_id)
        self.handle_bye(conn, tournament_id)
        return tree

    def handle_bye(self, conn: sqlite3.Connection, tournament_id: int) -> dict:
        self.validate_config(conn, tournament_id)
        # 既有 knockout 服务在建签时完成 WALKOVER 自动晋级。此处只提供统一契约
        # 下的可观察结果，不再生成第二套 BYE 算法。
        walkovers = [
            match["id"]
            for match in repo.list_matches(conn, tournament_id, MatchStage.KNOCKOUT.value)
            if match["bracket"] == MatchBracket.MAIN.value
            and match["status"] == MatchStatus.FINISHED.value
            and match.get("result_type") == "WALKOVER"
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

        group_matches = repo.list_matches(conn, tournament_id, MatchStage.GROUP.value)
        all_finished = all(
            match["status"] == MatchStatus.FINISHED.value for match in group_matches
        )
        state = "KNOCKOUT_READY" if all_finished else "GROUP_STAGE_IN_PROGRESS"
        return {"state": state, "can_advance": all_finished, "completed": False}


_HANDLERS: dict[str, FormatHandler] = {GROUP_KNOCKOUT: GroupKnockoutHandler()}


def resolve_format_handler(format_code: str) -> FormatHandler:
    """集中解析已支持赛制；禁止把未知 code 静默回退到小组淘汰。"""
    try:
        return _HANDLERS[format_code]
    except KeyError as exc:
        raise UnsupportedFormatError(format_code) from exc
