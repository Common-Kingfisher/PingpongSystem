"""公开报名与确认入赛服务。

公开入口只创建待确认台账；管理员确认时才在同一个 ``BEGIN IMMEDIATE``
事务内创建正式 Player 并标记 Registration，避免半状态和并发重复入赛。
"""

from __future__ import annotations

import sqlite3

from .. import repository as repo
from ..models import EventType, RegistrationStatus, TournamentStage
from . import players as players_service
from .transaction import TransactionBusyError, write_transaction


class RegistrationError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def _closed_message(tournament: dict) -> str:
    if tournament["stage"] != TournamentStage.REGISTRATION.value:
        return "赛事已开赛，报名已关闭"
    if tournament["roster_confirmed"]:
        return "参赛名单已确认，报名已关闭"
    return "赛事报名未开启"


def update_registration_setting(
    conn: sqlite3.Connection, tournament_id: int, *, enabled: bool
) -> dict:
    """修改公开报名开关。

    开启操作必须与名单确认/阶段变更串行化，避免过期页面绕过前端禁用态。
    关闭始终允许，便于清理历史上留下的原始开启标记。
    """
    try:
        with write_transaction(conn, busy_message="报名设置繁忙，请稍后重试"):
            tournament = repo.get_tournament(conn, tournament_id)
            if tournament is None:
                raise RegistrationError(404, "RESOURCE_NOT_FOUND", "资源不存在")
            if enabled and (
                tournament["stage"] != TournamentStage.REGISTRATION.value
                or tournament["roster_confirmed"]
            ):
                raise RegistrationError(
                    409, "REGISTRATION_CLOSED", _closed_message(tournament)
                )
            updated = repo.set_tournament_registration_enabled(
                conn, tournament_id, enabled
            )
            assert updated is not None
            return updated
    except TransactionBusyError as exc:
        raise RegistrationError(409, "TRANSACTION_BUSY", str(exc)) from None


def create_pending_registration(
    conn: sqlite3.Connection,
    tournament_id: int,
    *,
    name: str,
    affiliation: str | None,
    contact: str | None,
    rating_points: int,
) -> dict:
    """匿名提交报名；只落 PENDING，不创建 Player/Entry。"""
    try:
        with write_transaction(conn, busy_message="报名提交繁忙，请稍后重试"):
            tournament = repo.get_tournament(conn, tournament_id)
            if tournament is None:
                raise RegistrationError(404, "RESOURCE_NOT_FOUND", "资源不存在")
            if tournament["event_type"] == EventType.TEAM.value:
                raise RegistrationError(
                    409,
                    "UNSUPPORTED_REGISTRATION_EVENT_TYPE",
                    "团体赛暂不支持公开个人报名",
                )
            if (
                not tournament["registration_enabled"]
                or tournament["stage"] != TournamentStage.REGISTRATION.value
                or tournament["roster_confirmed"]
            ):
                raise RegistrationError(
                    409, "REGISTRATION_CLOSED", _closed_message(tournament)
                )
            registration = repo.create_registration(
                conn,
                tournament_id,
                name=name,
                affiliation=affiliation,
                contact=contact,
                rating_points=rating_points,
            )
    except Exception as exc:
        if isinstance(exc, TransactionBusyError):
            raise RegistrationError(409, "REGISTRATION_BUSY", str(exc)) from None
        raise
    return registration


def confirm_registration(
    conn: sqlite3.Connection,
    tournament_id: int,
    registration_id: int,
    *,
    confirmed_by_user_id: int,
) -> tuple[dict, dict]:
    """原子确认报名并创建正式 Player。"""
    try:
        with write_transaction(conn, busy_message="报名确认繁忙，请稍后重试"):
            tournament = repo.get_tournament(conn, tournament_id)
            if tournament is None:
                raise RegistrationError(404, "RESOURCE_NOT_FOUND", "资源不存在")

            registration = repo.get_registration(conn, registration_id)
            if registration is None or registration["tournament_id"] != tournament_id:
                raise RegistrationError(
                    404, "REGISTRATION_NOT_FOUND", "报名记录不存在"
                )
            if registration["status"] != RegistrationStatus.PENDING.value:
                raise RegistrationError(
                    409,
                    "REGISTRATION_ALREADY_PROCESSED",
                    "该报名已处理，不能重复确认",
                )

            try:
                players_service.ensure_players_editable(conn, tournament_id)
                players_service.ensure_player_capacity(
                    len(repo.list_players(conn, tournament_id)), additions=1
                )
            except players_service.PlayerError as exc:
                raise RegistrationError(409, "ROSTER_LOCKED", str(exc)) from None

            player = repo.add_player(
                conn,
                tournament_id,
                registration["name"],
                registration["affiliation"],
                registration["rating_points"],
            )
            confirmed = repo.confirm_registration(
                conn,
                registration_id,
                player_id=player["id"],
                confirmed_by_user_id=confirmed_by_user_id,
            )
            if confirmed is None:
                raise RegistrationError(
                    409,
                    "REGISTRATION_ALREADY_PROCESSED",
                    "该报名已处理，不能重复确认",
                )
            return confirmed, player
    except Exception as exc:
        if isinstance(exc, TransactionBusyError):
            raise RegistrationError(409, "TRANSACTION_BUSY", str(exc)) from None
        raise
