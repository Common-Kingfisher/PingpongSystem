"""赛事协作管理员授权服务：角色校验、Owner 保护和事务提交。"""

from __future__ import annotations

import sqlite3

from .. import repository as repo
from ..models import SystemRole, TournamentRole


GRANTABLE_TOURNAMENT_ROLES = frozenset(
    {
        TournamentRole.ADMIN.value,
        TournamentRole.OPERATOR.value,
        TournamentRole.VIEWER.value,
    }
)
RESOURCE_NOT_FOUND_MESSAGE = "资源不存在"


class TournamentAdminError(RuntimeError):
    """协作管理员业务错误，由 Router 转换成稳定 JSON 错误。"""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _resource_not_found() -> TournamentAdminError:
    return TournamentAdminError(404, "RESOURCE_NOT_FOUND", RESOURCE_NOT_FOUND_MESSAGE)


def _owner_protected() -> TournamentAdminError:
    return TournamentAdminError(409, "OWNER_PROTECTED", "赛事 Owner 不能通过此接口变更")


def list_tournament_admins(
    conn: sqlite3.Connection, tournament_id: int
) -> list[dict]:
    if repo.get_tournament(conn, tournament_id) is None:
        raise _resource_not_found()
    return repo.list_tournament_admins(conn, tournament_id)


def grant_tournament_admin(
    conn: sqlite3.Connection,
    *,
    tournament_id: int,
    user_id: int,
    role: str,
    actor_user_id: int,
) -> dict:
    """新增或更新普通赛事授权；重复授权仅更新角色，不产生重复行。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise _resource_not_found()
    if tournament.get("owner_user_id") == user_id:
        raise _owner_protected()
    if role not in GRANTABLE_TOURNAMENT_ROLES:
        raise TournamentAdminError(422, "INVALID_TOURNAMENT_ROLE", "赛事角色无效")

    target = repo.get_user_by_id(conn, user_id)
    if (
        target is None
        or not bool(target.get("active"))
        or target.get("system_role") != SystemRole.EVENT_ADMIN.value
    ):
        # 不暴露目标账号是否存在、是否停用或其系统角色。
        raise _resource_not_found()

    try:
        repo.upsert_tournament_admin(
            conn,
            tournament_id,
            user_id,
            role,
            created_by_user_id=actor_user_id,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    granted = repo.get_tournament_admin(conn, tournament_id, user_id)
    if granted is None:  # pragma: no cover - 数据库成功写入后不应发生
        raise _resource_not_found()
    return granted


def revoke_tournament_admin(
    conn: sqlite3.Connection,
    *,
    tournament_id: int,
    user_id: int,
) -> None:
    """软撤销普通授权；重复撤销仍返回成功。"""
    tournament = repo.get_tournament(conn, tournament_id)
    if tournament is None:
        raise _resource_not_found()
    if tournament.get("owner_user_id") == user_id:
        raise _owner_protected()

    try:
        repo.revoke_tournament_admin(conn, tournament_id, user_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
