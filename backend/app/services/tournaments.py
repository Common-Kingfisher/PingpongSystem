"""赛事服务：创建赛事（含自动生成球台）等事务性编排。"""

import sqlite3
from typing import Any

from .. import repository as repo
from ..models import TournamentRole
from . import formats


INITIAL_RULE_VERSION = 1


class TournamentFormatError(Exception):
    """赛制配置更新时的可预期业务错误。"""

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _validate_rule_config(rule_config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rule_config, dict):
        raise TournamentFormatError("rule_config 必须是 JSON object", 422)
    try:
        repo.encode_rule_config(rule_config)
    except repo.RuleConfigError as exc:
        raise TournamentFormatError(str(exc), 422) from exc
    return rule_config


def _begin_format_transaction(conn: sqlite3.Connection) -> bool:
    """返回 True 表示本函数取得独立事务，需要负责 commit/rollback。"""
    if conn.in_transaction:
        conn.execute("SAVEPOINT tournament_format_update")
        return False
    conn.execute("BEGIN IMMEDIATE")
    return True


def _finish_format_transaction(conn: sqlite3.Connection, owns_transaction: bool) -> None:
    if owns_transaction:
        conn.commit()
    else:
        conn.execute("RELEASE SAVEPOINT tournament_format_update")


def _rollback_format_transaction(conn: sqlite3.Connection, owns_transaction: bool) -> None:
    if owns_transaction:
        conn.rollback()
    else:
        conn.execute("ROLLBACK TO SAVEPOINT tournament_format_update")
        conn.execute("RELEASE SAVEPOINT tournament_format_update")


def create_tournament_with_tables(
    conn: sqlite3.Connection,
    name: str,
    date,
    table_count: int,
    group_count: int,
    qualify_per_group: int,
    event_type: str = "SINGLES",
    bronze_mode: str = "JOINT_BRONZE",
    placement_mode: str = "OFF",
    games_to_win: int = 2,
    points_to_win: int = 11,
    operation_mode: str = "LIVE",
    owner_user_id: int | None = None,
    format_code: str | None = None,
    rule_config: dict[str, Any] | None = None,
    registration_enabled: bool = False,
) -> dict:
    """在同一个事务中创建赛事、赛事 Owner 授权和球台。"""
    handler = formats.resolve_format_handler(format_code) if format_code else None
    if format_code is None and rule_config not in (None, {}):
        raise TournamentFormatError("未指定 format_code 时不能写入 rule_config", 422)
    if format_code is None:
        normalized_rule_config = None
        rule_version = None
    else:
        normalized_rule_config = _validate_rule_config(rule_config or {})
        rule_version = INITIAL_RULE_VERSION

    try:
        tournament = repo.create_tournament(
            conn,
            name,
            date.isoformat(),
            table_count,
            group_count,
            qualify_per_group,
            event_type,
            bronze_mode,
            placement_mode,
            games_to_win,
            points_to_win,
            operation_mode,
            owner_user_id=owner_user_id,
            format_code=format_code,
            rule_config=normalized_rule_config,
            rule_version=rule_version,
            registration_enabled=registration_enabled,
        )
        if handler is not None:
            handler.validate_config(conn, tournament["id"])
        if owner_user_id is not None:
            repo.upsert_tournament_admin(
                conn,
                tournament["id"],
                owner_user_id,
                TournamentRole.OWNER.value,
                created_by_user_id=owner_user_id,
            )
        repo.create_tables_for_tournament(conn, tournament["id"], table_count)
        conn.commit()
        return tournament
    except Exception:
        conn.rollback()
        raise


def update_format_config(
    conn: sqlite3.Connection,
    tournament_id: int,
    format_code: str,
    rule_config: dict[str, Any],
) -> dict:
    """校验并原子更新 Tournament 的赛制三元组。"""
    normalized_rule_config = _validate_rule_config(rule_config)
    handler = formats.resolve_format_handler(format_code)
    owns_transaction = _begin_format_transaction(conn)
    try:
        tournament = repo.get_tournament(conn, tournament_id)
        if tournament is None:
            raise TournamentFormatError("赛事不存在", 404)
        if repo.count_matches(conn, tournament_id) or repo.count_team_ties(
            conn, tournament_id
        ):
            raise TournamentFormatError(
                "赛事已产生比赛或团体对抗，不能静默更换赛制或关键规则", 409
            )

        updated = repo.update_tournament_format_config(
            conn,
            tournament_id,
            format_code=format_code,
            rule_config=normalized_rule_config,
            rule_version=INITIAL_RULE_VERSION,
        )
        if updated is None:
            raise TournamentFormatError("赛事不存在", 404)

        # B 侧 validator 读取已写入的候选配置；失败时回滚三元组，不留下半套数据。
        handler.validate_config(conn, tournament_id)
        refreshed = repo.get_tournament(conn, tournament_id)
        if refreshed is None:
            raise TournamentFormatError("赛事不存在", 404)
        _finish_format_transaction(conn, owns_transaction)
        return refreshed
    except Exception:
        _rollback_format_transaction(conn, owns_transaction)
        raise
