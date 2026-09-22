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
    参数非法、已存在子资源的归属冲突一律按资源不存在处理；子资源不存在时，
    若路径已给出 ``tournament_id``，则以该赛事作为授权目标（具体是 404 还是
    业务 409 交给业务层判断），否则同样按资源不存在处理。
    """
    path_params = request.path_params
    resolved: list[int] = []

    def _collect(resource: dict[str, Any] | None) -> None:
        """收集子资源所属赛事。

        子资源不存在时不在这里下结论：若路径同时给出 ``tournament_id``，
        授权目标就是该赛事，具体 404/409 由业务层决定；若路径只有子资源
        ID，则最终没有可解析的赛事，仍按资源不存在处理。
        """
        tournament_id = _parse_int(resource.get("tournament_id")) if resource else None
        if tournament_id is not None:
            resolved.append(tournament_id)

    def _collect_rubber(raw_id: Any) -> None:
        rubber_id = _parse_int(raw_id)
        rubber = repo.get_team_rubber(conn, rubber_id) if rubber_id is not None else None
        tie_id = _parse_int(rubber.get("team_tie_id")) if rubber else None
        tie = repo.get_team_tie(conn, tie_id) if tie_id is not None else None
        _collect(tie)

    if "match_id" in path_params:
        match_id = _parse_int(path_params["match_id"])
        _collect(repo.get_match(conn, match_id) if match_id is not None else None)

    if "tie_id" in path_params:
        tie_id = _parse_int(path_params["tie_id"])
        _collect(repo.get_team_tie(conn, tie_id) if tie_id is not None else None)

    if "rubber_id" in path_params:
        _collect_rubber(path_params["rubber_id"])

    if "group_id" in path_params:
        group_id = _parse_int(path_params["group_id"])
        _collect(repo.get_group(conn, group_id) if group_id is not None else None)

    if "entry_id" in path_params:
        entry_id = _parse_int(path_params["entry_id"])
        _collect(repo.get_entry(conn, entry_id) if entry_id is not None else None)

    if "player_id" in path_params:
        player_id = _parse_int(path_params["player_id"])
        _collect(repo.get_player(conn, player_id) if player_id is not None else None)

    if "table_id" in path_params:
        table_id = _parse_int(path_params["table_id"])
        _collect(repo.get_table(conn, table_id) if table_id is not None else None)

    if "tournament_id" in path_params:
        tournament_id = _parse_int(path_params["tournament_id"])
        if tournament_id is None:
            return None
        # 路径里的赛事就是授权目标；已能解析出的子资源必须与它归属一致，
        # 否则（例如伪造其他赛事的子资源 ID）按资源不存在处理。
        if any(item != tournament_id for item in resolved):
            return None
        return tournament_id

    if not resolved:
        return None
    # 同一个请求里解析出的多个子资源必须属于同一赛事，否则按资源不存在处理。
    if any(item != resolved[0] for item in resolved):
        return None
    return resolved[0]


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


def require_public_tournament_read(
    request: Request,
    conn: Connection = Depends(get_db),
) -> None:
    """校验 Public 只读目标赛事存在，但不要求登录或赛事管理授权。

    该依赖只用于冻结的 Public 页面实际依赖的赛事级只读 GET。管理端 Export、
    审计、排程估算等敏感读取仍必须使用 ``require_tournament_read``。
    """
    tournament_id = _lookup_tournament_id(request, conn)
    if tournament_id is None or repo.get_tournament(conn, tournament_id) is None:
        raise _error(404, "RESOURCE_NOT_FOUND", "资源不存在")


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
    "require_public_tournament_read",
    "require_system_admin",
    "require_tournament_read",
    "require_tournament_write",
]
