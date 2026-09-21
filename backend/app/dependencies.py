"""A2.4 统一鉴权依赖：系统角色与赛事级资源授权。

本模块复用 A2.3 的认证依赖函数对象，不复制认证逻辑。这样，现有认证
Router 与后续赛事 Router 通过同一个 ``get_current_user`` 依赖完成认证，
FastAPI 仍可在同一请求内复用依赖结果，避免重复查询用户和 Session。

赛事权限只来自赛事 Owner 或有效的 ``tournament_admins`` 授权；系统角色
不会自动转换为赛事写权限。
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from fastapi import Depends, Request

from . import repository as repo
from .auth_dependencies import (
    AuthContext,
    _error,
    extract_session_token,
    get_current_user,
    require_system_admin,
)
from .db import get_db
from .models import SystemRole, TournamentRole


WRITE_TOURNAMENT_ROLES = frozenset(
    {
        TournamentRole.OWNER.value,
        TournamentRole.ADMIN.value,
        TournamentRole.OPERATOR.value,
    }
)
READ_TOURNAMENT_ROLES = frozenset(role.value for role in TournamentRole)


def require_event_admin(
    context: AuthContext = Depends(get_current_user),
) -> AuthContext:
    """只允许系统角色为 EVENT_ADMIN 的账号进入赛事创建/管理入口。"""
    if context.user.get("system_role") != SystemRole.EVENT_ADMIN.value:
        raise _error(403, "FORBIDDEN", "需要赛事管理员权限")
    return context


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _lookup_tournament_id(request: Request, conn: Connection) -> int | None:
    """从路径参数解析所属赛事，不信任客户端额外传入的赛事 ID。

    支持直接使用 ``tournament_id``，也支持现有路由中的资源 ID 反查。
    任何资源不存在、参数非法或同一请求中的资源归属冲突都按资源不存在处理。
    """
    path_params = request.path_params
    resolved: list[int] = []

    if "match_id" in path_params:
        match_id = _parse_int(path_params["match_id"])
        match = repo.get_match(conn, match_id) if match_id is not None else None
        tournament_id = _parse_int(match.get("tournament_id")) if match else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "tie_id" in path_params:
        tie_id = _parse_int(path_params["tie_id"])
        tie = repo.get_team_tie(conn, tie_id) if tie_id is not None else None
        tournament_id = _parse_int(tie.get("tournament_id")) if tie else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "rubber_id" in path_params:
        rubber_id = _parse_int(path_params["rubber_id"])
        rubber = repo.get_team_rubber(conn, rubber_id) if rubber_id is not None else None
        tie_id = _parse_int(rubber.get("team_tie_id")) if rubber else None
        tie = repo.get_team_tie(conn, tie_id) if tie_id is not None else None
        tournament_id = _parse_int(tie.get("tournament_id")) if tie else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "group_id" in path_params:
        group_id = _parse_int(path_params["group_id"])
        group = repo.get_group(conn, group_id) if group_id is not None else None
        tournament_id = _parse_int(group.get("tournament_id")) if group else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "entry_id" in path_params:
        entry_id = _parse_int(path_params["entry_id"])
        entry = repo.get_entry(conn, entry_id) if entry_id is not None else None
        tournament_id = _parse_int(entry.get("tournament_id")) if entry else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "player_id" in path_params:
        player_id = _parse_int(path_params["player_id"])
        player = repo.get_player(conn, player_id) if player_id is not None else None
        tournament_id = _parse_int(player.get("tournament_id")) if player else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "table_id" in path_params:
        table_id = _parse_int(path_params["table_id"])
        table = repo.get_table(conn, table_id) if table_id is not None else None
        tournament_id = _parse_int(table.get("tournament_id")) if table else None
        if tournament_id is None:
            return None
        resolved.append(tournament_id)

    if "tournament_id" in path_params:
        tournament_id = _parse_int(path_params["tournament_id"])
        if tournament_id is None:
            return None
        if any(item != tournament_id for item in resolved):
            return None
        return tournament_id

    return resolved[0] if resolved else None


def get_tournament_access(
    request: Request,
    context: AuthContext = Depends(get_current_user),
    conn: Connection = Depends(get_db),
) -> dict[str, Any]:
    """解析目标赛事并校验当前用户是否拥有该赛事的任一授权角色。"""
    tournament_id = _lookup_tournament_id(request, conn)
    if tournament_id is None:
        raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")

    access = repo.get_tournament_access(
        conn, tournament_id, int(context.user["id"])
    )
    if access is None:
        raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
    return {**access, "user": context.user}


def require_tournament_read(
    access: dict[str, Any] = Depends(get_tournament_access),
) -> dict[str, Any]:
    if access.get("role") not in READ_TOURNAMENT_ROLES:
        raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
    return access


def require_tournament_write(
    access: dict[str, Any] = Depends(get_tournament_access),
) -> dict[str, Any]:
    if access.get("role") not in WRITE_TOURNAMENT_ROLES:
        raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")
    return access


__all__ = [
    "AuthContext",
    "READ_TOURNAMENT_ROLES",
    "WRITE_TOURNAMENT_ROLES",
    "extract_session_token",
    "get_current_user",
    "get_tournament_access",
    "require_event_admin",
    "require_system_admin",
    "require_tournament_read",
    "require_tournament_write",
]
