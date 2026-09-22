"""A2.6 认证 OpenAPI 契约元数据与文档辅助。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from . import schemas


OPENAPI_CONTRACT_VERSION = "0.2.0"
OPENAPI_AUTH_CONTRACT = "A2.6"

AUTH_SECURITY_REQUIREMENTS = [
    {"sessionCookie": []},
    {"bearerAuth": []},
]

SET_SESSION_COOKIE_HEADER = {
    "description": (
        "仅 browser 登录成功时设置。Cookie 名为 pp_session，"
        "属性为 HttpOnly、SameSite=Lax、Path=/；HTTPS 追加 Secure。"
    ),
    "schema": {"type": "string"},
}

CLEAR_SESSION_COOKIE_HEADER = {
    "description": "成功响应中删除 pp_session Cookie。",
    "schema": {"type": "string"},
}

OPENAPI_DESCRIPTION = """\
A 轨 D2/D3 认证、授权、Bootstrap、系统用户与协作管理员契约。

D3A 协作管理员接口：
- `GET /api/tournaments/{tournament_id}/admins`：Owner / Admin 查询授权。
- `POST /api/tournaments/{tournament_id}/admins`：Owner / Admin 新增或更新
  `ADMIN / OPERATOR / VIEWER` 授权。
- `DELETE /api/tournaments/{tournament_id}/admins/{user_id}`：Owner / Admin
  软撤销普通授权。
- `OWNER` 只来自 `tournaments.owner_user_id`，不能通过普通授权接口授予或撤销。
- 目标账号必须是存在、有效、`active=true` 的 `EVENT_ADMIN`。
- Operator / Viewer 或无赛事权限统一按 404 `RESOURCE_NOT_FOUND` 防泄漏。

认证方式：
- browser 登录成功只通过 Set-Cookie 建立 `pp_session` 会话，不返回 access_token；
  Cookie 属性固定为 HttpOnly、SameSite=Lax、Path=/，HTTPS 环境追加 Secure。
- bearer 登录成功返回不透明 `access_token`，客户端使用 `Authorization: Bearer <token>`。
- 同一请求同时携带 Cookie 与 Bearer 且指向不同会话时必须返回 401 `AUTH_REQUIRED`。
- 账号 `active=false`、会话撤销、过期或改密后，旧 Cookie/Bearer 均返回 401 `AUTH_REQUIRED`。
- logout 对无凭据、未知凭据或已撤销凭据保持幂等 204；冲突凭据必须返回 401 `AUTH_REQUIRED`。

Bootstrap：
- 状态固定为 `NEEDS_INITIALIZATION`、`READY`、`RECOVERY_REQUIRED`。
- `GET /api/v1/system/bootstrap/status` 为只读分流接口，不返回账号、路径或恢复信息。
- `POST /api/v1/system/bootstrap` 仅服务器本机 socket 客户端可调用；非本机返回 404 `RESOURCE_NOT_FOUND`。
- 初始化完成后 Web bootstrap 永久关闭；无可用 SYSTEM_ADMIN 时只进入 recovery，不重新开放 C 轨 `/setup` 写入口。

前端消费边界：
- C 轨只消费后端返回的允许、只读、无权限结果；不实现复杂权限编辑器。
- 真实权限始终以后端判定为准，前端不得根据角色名称自行推导资源权限。
- browser Cookie 默认走同源或 Vite `/api` proxy；当前 CORS 未开启 credentials，C 轨不得依赖跨源 Cookie。
- 跨源 Cookie 需求必须先单独评审 CORS、SameSite、CSRF 与 HTTPS 边界，再升级本 contract。

变更机制：
- 本文件冻结后，任何字段、状态枚举或错误码变化必须先更新版本化契约与变更说明，再通知 C 轨。
- 未产生新的版本化说明前，不得静默破坏现有 contract。
"""

CONTRACT_METADATA: dict[str, Any] = {
    "version": OPENAPI_CONTRACT_VERSION,
    "frozen_by": OPENAPI_AUTH_CONTRACT,
    "session": {
        "cookie": {
            "name": "pp_session",
            "http_only": True,
            "same_site": "Lax",
            "path": "/",
            "secure": "https_only",
        },
        "bearer": {
            "scheme": "bearer",
            "token_type": "opaque",
        },
        "conflict": {"status": 401, "code": "AUTH_REQUIRED"},
        "inactive_user": {"status": 401, "code": "AUTH_REQUIRED"},
        "logout_idempotent_without_credentials": True,
    },
    "bootstrap": {
        "states": [
            "NEEDS_INITIALIZATION",
            "READY",
            "RECOVERY_REQUIRED",
        ],
        "status_endpoint": "/api/v1/system/bootstrap/status",
        "write_endpoint": "/api/v1/system/bootstrap",
        "write_endpoint_local_only": True,
        "non_local_status": 404,
        "non_local_code": "RESOURCE_NOT_FOUND",
        "web_bootstrap_reopens_after_initialization": False,
    },
    "frontend_boundary": {
        "consumer": "C",
        "accepted_backend_results": ["allowed", "read_only", "no_access"],
        "complex_permission_editor": False,
        "browser_cookie_transport": "same_origin_or_vite_proxy",
        "cross_origin_credentials_supported": False,
    },
    "change_policy": {
        "requires_versioned_contract_update": True,
        "requires_change_note": True,
        "notify_consumer": "C",
        "breaking_changes_require_new_contract_version": True,
    },
    "tournament_admins": {
        "manage_roles": ["OWNER", "ADMIN"],
        "grantable_roles": ["ADMIN", "OPERATOR", "VIEWER"],
        "owner_source": "tournaments.owner_user_id",
        "owner_protected": {"status": 409, "code": "OWNER_PROTECTED"},
        "no_access_status": 404,
        "target_requirements": {
            "active": True,
            "system_role": "EVENT_ADMIN",
        },
    },
}

_SECURED_OPERATIONS = {
    ("/api/v1/auth/me", "get"),
    ("/api/v1/auth/change-password", "post"),
    ("/api/v1/system/users", "post"),
    ("/api/tournaments/{tournament_id}/admins", "get"),
    ("/api/tournaments/{tournament_id}/admins", "post"),
    ("/api/tournaments/{tournament_id}/admins/{user_id}", "delete"),
}


def error_response(
    description: str,
    *,
    codes: list[str],
    example_code: str | None = None,
    example_message: str = "请求未完成",
) -> dict[str, Any]:
    """构造稳定的业务错误响应文档，业务错误统一使用 detail.code/message。"""
    code = example_code or codes[0]
    return {
        "description": description,
        "model": schemas.ApiErrorResponse,
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": code,
                        "message": example_message,
                    }
                }
            }
        },
        "x-error-codes": codes,
    }


def install_openapi_contract(app: FastAPI) -> None:
    """给 FastAPI 生成结果补充认证契约，不改变实际路由行为。"""
    original_openapi = app.openapi

    def contract_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema

        schema = original_openapi()
        info = schema.setdefault("info", {})
        info["version"] = OPENAPI_CONTRACT_VERSION
        info["description"] = OPENAPI_DESCRIPTION
        schema["x-contract"] = CONTRACT_METADATA

        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["sessionCookie"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "pp_session",
            "description": "browser 登录建立的 HttpOnly 服务端会话 Cookie。",
        }
        security_schemes["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "opaque session token",
            "description": "bearer 登录返回的不透明服务端会话 Token。",
        }

        for path, path_item in schema.get("paths", {}).items():
            for method, operation in path_item.items():
                if (path, method) in _SECURED_OPERATIONS:
                    operation["security"] = AUTH_SECURITY_REQUIREMENTS

        app.openapi_schema = schema
        return schema

    app.openapi = contract_openapi  # type: ignore[method-assign]
