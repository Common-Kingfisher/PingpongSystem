"""A2.6 认证 OpenAPI 契约冻结测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "docs" / "openapi-v0.2.json"

AUTH_OPERATIONS = {
    "/api/v1/auth/login": "post",
    "/api/v1/auth/logout": "post",
    "/api/v1/auth/me": "get",
    "/api/v1/auth/change-password": "post",
    "/api/v1/system/bootstrap/status": "get",
    "/api/v1/system/bootstrap": "post",
    "/api/v1/system/users": "post",
}

TOURNAMENT_ADMIN_OPERATIONS = {
    ("/api/tournaments/{tournament_id}/admins", "get"),
    ("/api/tournaments/{tournament_id}/admins", "post"),
    ("/api/tournaments/{tournament_id}/admins/{user_id}", "delete"),
}

SECURED_OPERATIONS = {
    ("/api/v1/auth/me", "get"),
    ("/api/v1/auth/change-password", "post"),
    ("/api/v1/system/users", "post"),
    *TOURNAMENT_ADMIN_OPERATIONS,
}


def _schema() -> dict:
    return app.openapi()


def _operation(path: str, method: str) -> dict:
    return _schema()["paths"][path][method]


def _component(name: str) -> dict:
    return _schema()["components"]["schemas"][name]


def _properties(name: str) -> set[str]:
    return set(_component(name)["properties"])


def _error_codes(path: str, method: str, status: str) -> set[str]:
    response = _operation(path, method)["responses"][status]
    return set(response.get("x-error-codes", []))


def test_auth_contract_exposes_all_frozen_operations():
    paths = _schema()["paths"]

    for path, method in AUTH_OPERATIONS.items():
        assert path in paths, path
        assert method in paths[path], (path, method)

    for path, method in TOURNAMENT_ADMIN_OPERATIONS:
        assert path in paths, path
        assert method in paths[path], (path, method)


def test_auth_request_and_response_dtos_are_frozen():
    assert _properties("AuthLoginRequest") == {"username", "password", "mode"}
    assert set(_component("AuthLoginRequest")["required"]) == {
        "username",
        "password",
    }
    mode = _component("AuthLoginRequest")["properties"]["mode"]
    assert mode["enum"] == ["browser", "bearer"]
    assert mode["default"] == "browser"

    assert _properties("AuthUserOut") == {
        "id",
        "username",
        "display_name",
        "system_role",
    }
    assert _properties("AuthLoginResponse") == {
        "access_token",
        "token_type",
        "expires_at",
        "user",
    }
    assert _properties("AuthMeResponse") == {
        "user",
        "tournament_access_count",
    }
    assert _properties("AuthChangePasswordRequest") == {
        "current_password",
        "new_password",
    }

    assert _properties("BootstrapRequest") == {
        "username",
        "display_name",
        "password",
        "phone",
        "note",
    }
    assert _properties("BootstrapResponse") == {
        "id",
        "username",
        "display_name",
        "system_role",
    }
    assert _properties("EventAdminCreateRequest") == {
        "username",
        "display_name",
        "password",
        "phone",
        "note",
    }
    assert _properties("EventAdminOut") == {
        "id",
        "username",
        "display_name",
        "system_role",
        "phone",
        "note",
    }

    assert _properties("TournamentAdminGrantRequest") == {"user_id", "role"}
    assert set(_component("TournamentAdminGrantRequest")["required"]) == {
        "user_id",
        "role",
    }
    assert _component("TournamentAdminGrantRequest")["properties"]["role"][
        "enum"
    ] == ["ADMIN", "OPERATOR", "VIEWER"]
    assert _properties("TournamentAdminOut") == {
        "user_id",
        "username",
        "display_name",
        "role",
        "active",
        "is_owner",
        "created_at",
        "created_by_user_id",
    }


def test_response_dtos_do_not_expose_password_or_token_hashes():
    forbidden = {"password", "password_hash", "token_hash"}
    response_models = {
        "AuthUserOut": {"id", "username", "display_name", "system_role"},
        "AuthMeResponse": {"user", "tournament_access_count"},
        "AuthLoginResponse": {
            "access_token",
            "token_type",
            "expires_at",
            "user",
        },
        "BootstrapResponse": {
            "id",
            "username",
            "display_name",
            "system_role",
        },
        "EventAdminOut": {
            "id",
            "username",
            "display_name",
            "system_role",
            "phone",
            "note",
        },
        "TournamentAdminOut": {
            "user_id",
            "username",
            "display_name",
            "role",
            "active",
            "is_owner",
            "created_at",
            "created_by_user_id",
        },
    }

    for model_name, expected in response_models.items():
        properties = _properties(model_name)
        assert properties == expected
        assert properties.isdisjoint(forbidden)


def test_bootstrap_contract_freezes_states_and_local_only_boundary():
    status_schema = _component("BootstrapStatus")
    assert status_schema["enum"] == [
        "NEEDS_INITIALIZATION",
        "READY",
        "RECOVERY_REQUIRED",
    ]

    status_operation = _operation("/api/v1/system/bootstrap/status", "get")
    assert status_operation["x-bootstrap-status-states"] == status_schema["enum"]
    assert status_operation["x-bootstrap-write-endpoint"] == (
        "/api/v1/system/bootstrap"
    )

    bootstrap = _operation("/api/v1/system/bootstrap", "post")
    assert bootstrap["x-local-only"] is True
    assert bootstrap["x-non-local-status"] == 404
    assert bootstrap["x-non-local-code"] == "RESOURCE_NOT_FOUND"
    assert _error_codes(
        "/api/v1/system/bootstrap", "post", "404"
    ) == {"RESOURCE_NOT_FOUND"}

    metadata = _schema()["x-contract"]["bootstrap"]
    assert metadata["states"] == status_schema["enum"]
    assert metadata["write_endpoint_local_only"] is True
    assert metadata["web_bootstrap_reopens_after_initialization"] is False
    assert "/setup" in _schema()["info"]["description"]
    assert "仅服务器本机" in _schema()["info"]["description"]


def test_auth_security_schemes_and_endpoint_requirements_are_frozen():
    schemes = _schema()["components"]["securitySchemes"]
    assert schemes["sessionCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "pp_session",
        "description": "browser 登录建立的 HttpOnly 服务端会话 Cookie。",
    }
    assert schemes["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "opaque session token",
        "description": "bearer 登录返回的不透明服务端会话 Token。",
    }

    expected_security = [{"sessionCookie": []}, {"bearerAuth": []}]
    for path, method in SECURED_OPERATIONS:
        assert _operation(path, method)["security"] == expected_security

    logout = _operation("/api/v1/auth/logout", "post")
    assert logout["x-auth-behavior"]["credentials"] == "optional"
    assert logout["x-auth-behavior"]["idempotent_without_valid_credentials"] is True
    assert logout["x-auth-behavior"]["credential_conflict"] == {
        "status": 401,
        "code": "AUTH_REQUIRED",
    }


def test_auth_error_codes_are_frozen_by_operation_and_status():
    expected = {
        ("/api/v1/auth/login", "post", "401"): {"AUTH_INVALID_CREDENTIALS"},
        ("/api/v1/auth/logout", "post", "401"): {"AUTH_REQUIRED"},
        ("/api/v1/auth/me", "get", "401"): {"AUTH_REQUIRED"},
        ("/api/v1/auth/change-password", "post", "401"): {
            "AUTH_REQUIRED",
            "AUTH_INVALID_CREDENTIALS",
        },
        ("/api/v1/system/bootstrap/status", "get", "500"): {
            "SYSTEM_STATE_MISSING"
        },
        ("/api/v1/system/bootstrap", "post", "404"): {
            "RESOURCE_NOT_FOUND"
        },
        ("/api/v1/system/bootstrap", "post", "409"): {
            "BOOTSTRAP_ALREADY_COMPLETED",
            "RECOVERY_REQUIRED",
            "USERNAME_ALREADY_EXISTS",
        },
        ("/api/v1/system/users", "post", "401"): {"AUTH_REQUIRED"},
        ("/api/v1/system/users", "post", "403"): {"FORBIDDEN"},
        ("/api/v1/system/users", "post", "409"): {
            "USERNAME_ALREADY_EXISTS"
        },
    }

    for (path, method, status), codes in expected.items():
        assert _error_codes(path, method, status) == codes, (path, status)

    assert _operation("/api/v1/auth/change-password", "post")[
        "x-business-error-codes"
    ] == {"422": ["INVALID_NEW_PASSWORD"]}
    assert _operation("/api/v1/system/bootstrap", "post")[
        "x-business-error-codes"
    ]["422"] == ["INVALID_BOOTSTRAP_INPUT", "INVALID_BOOTSTRAP_PASSWORD"]
    assert _operation("/api/v1/system/users", "post")[
        "x-business-error-codes"
    ]["422"] == [
        "INVALID_EVENT_ADMIN_INPUT",
        "INVALID_EVENT_ADMIN_PASSWORD",
    ]


def test_tournament_admin_contract_freezes_permissions_and_errors():
    list_operation = _operation(
        "/api/tournaments/{tournament_id}/admins", "get"
    )
    assert list_operation["x-permission"] == "tournament OWNER or ADMIN only"
    assert list_operation["x-owner-source"] == "tournaments.owner_user_id"
    assert _error_codes(
        "/api/tournaments/{tournament_id}/admins", "get", "401"
    ) == {"AUTH_REQUIRED"}
    assert _error_codes(
        "/api/tournaments/{tournament_id}/admins", "get", "404"
    ) == {"RESOURCE_NOT_FOUND"}

    grant_operation = _operation(
        "/api/tournaments/{tournament_id}/admins", "post"
    )
    assert grant_operation["x-permission"] == "tournament OWNER or ADMIN only"
    assert grant_operation["x-grantable-roles"] == [
        "ADMIN",
        "OPERATOR",
        "VIEWER",
    ]
    assert grant_operation["x-target-requirements"] == (
        "active EVENT_ADMIN user"
    )
    assert grant_operation["x-business-error-codes"] == {
        "422": ["INVALID_TOURNAMENT_ROLE"]
    }
    assert _error_codes(
        "/api/tournaments/{tournament_id}/admins", "post", "404"
    ) == {"RESOURCE_NOT_FOUND"}
    assert _error_codes(
        "/api/tournaments/{tournament_id}/admins", "post", "409"
    ) == {"OWNER_PROTECTED"}

    revoke_operation = _operation(
        "/api/tournaments/{tournament_id}/admins/{user_id}", "delete"
    )
    assert revoke_operation["x-permission"] == "tournament OWNER or ADMIN only"
    assert revoke_operation["x-idempotent"] is True
    assert revoke_operation["x-owner-source"] == "tournaments.owner_user_id"
    assert _error_codes(
        "/api/tournaments/{tournament_id}/admins/{user_id}", "delete", "404"
    ) == {"RESOURCE_NOT_FOUND"}
    assert _error_codes(
        "/api/tournaments/{tournament_id}/admins/{user_id}", "delete", "409"
    ) == {"OWNER_PROTECTED"}

    metadata = _schema()["x-contract"]["tournament_admins"]
    assert metadata == {
        "manage_roles": ["OWNER", "ADMIN"],
        "grantable_roles": ["ADMIN", "OPERATOR", "VIEWER"],
        "owner_source": "tournaments.owner_user_id",
        "owner_protected": {"status": 409, "code": "OWNER_PROTECTED"},
        "no_access_status": 404,
        "target_requirements": {
            "active": True,
            "system_role": "EVENT_ADMIN",
        },
    }


def test_cookie_behavior_and_active_false_semantics_are_documented():
    assert "Set-Cookie" in _operation("/api/v1/auth/login", "post")[
        "responses"
    ]["200"]["headers"]
    assert "Set-Cookie" in _operation("/api/v1/auth/logout", "post")[
        "responses"
    ]["204"]["headers"]
    assert "Set-Cookie" in _operation(
        "/api/v1/auth/change-password", "post"
    )["responses"]["204"]["headers"]

    metadata = _schema()["x-contract"]["session"]
    assert metadata["cookie"] == {
        "name": "pp_session",
        "http_only": True,
        "same_site": "Lax",
        "path": "/",
        "secure": "https_only",
    }
    assert metadata["conflict"] == {"status": 401, "code": "AUTH_REQUIRED"}
    assert metadata["inactive_user"] == {"status": 401, "code": "AUTH_REQUIRED"}


def test_frontend_contract_boundary_and_change_policy_are_explicit():
    metadata = _schema()["x-contract"]
    assert metadata["frontend_boundary"] == {
        "consumer": "C",
        "accepted_backend_results": ["allowed", "read_only", "no_access"],
        "complex_permission_editor": False,
        "browser_cookie_transport": "same_origin_or_vite_proxy",
        "cross_origin_credentials_supported": False,
    }
    assert "Vite `/api` proxy" in _schema()["info"]["description"]
    assert "跨源 Cookie" in _schema()["info"]["description"]
    policy = metadata["change_policy"]
    assert policy["requires_versioned_contract_update"] is True
    assert policy["requires_change_note"] is True
    assert policy["notify_consumer"] == "C"
    assert policy["breaking_changes_require_new_contract_version"] is True


def test_exported_openapi_snapshot_matches_runtime_contract():
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot == _schema()
