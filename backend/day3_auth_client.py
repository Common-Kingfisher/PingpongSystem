"""D 轨 Day3 验收：真实认证客户端（供 fixture 与后端授权验收复用）。

## 为什么需要它

master@81827b3 起，`POST /api/matches/{id}/score` 等写接口由
`require_tournament_write` 保护。旧的“后端没有 Auth”验收脚本因此失效。

本模块**只做两件事**：

1. 用真实 Bootstrap + 真实 `/api/v1/auth/login` 建立会话（Bearer 或 Cookie）；
2. 用真实 HTTP 调用业务接口。

**不**做任何绕过：没有 dependency override、没有 TEST_MODE、没有“本机/局域网就放行”、
没有直接调 service 层替 HTTP 写操作。测试前置账号通过真实
`POST /api/v1/system/bootstrap` 与 `POST /api/v1/system/users` 创建。
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request

BOOTSTRAP_USERNAME = "d3-boot-admin"
BOOTSTRAP_PASSWORD = "d3-bootstrap-pass1"


class ApiResult:
    def __init__(self, status: int, body, headers: dict[str, str]):
        self.status = status
        self.body = body
        self.headers = headers

    @property
    def detail_code(self) -> str | None:
        """结构化错误码（A 轨契约的 detail.code），旧式字符串 detail 时为 None。"""
        if isinstance(self.body, dict):
            detail = self.body.get("detail")
            if isinstance(detail, dict):
                code = detail.get("code")
                return code if isinstance(code, str) else None
        return None

    @property
    def detail_message(self) -> str | None:
        if isinstance(self.body, dict):
            detail = self.body.get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                return detail["message"]
        return None


class AuthClient:
    """真实认证的 HTTP 客户端：Bearer 与浏览器 Cookie 两种模式都用同一套代码。"""

    def __init__(self, base_url: str, token: str | None = None, use_cookies: bool = False):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.jar = http.cookiejar.CookieJar() if use_cookies else None
        handlers: list[urllib.request.BaseHandler] = []
        if self.jar is not None:
            handlers.append(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener = urllib.request.build_opener(*handlers)

    # ---------------------------------------------------------------- plumbing

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        token: str | None = None,
    ) -> ApiResult:
        data = None
        headers: dict[str, str] = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        effective_token = token if token is not None else self.token
        if effective_token is not None:
            headers["Authorization"] = f"Bearer {effective_token}"

        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else None
                return ApiResult(resp.status, parsed, dict(resp.headers))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            return ApiResult(exc.code, parsed, dict(exc.headers))

    def get(self, path: str, token: str | None = None) -> ApiResult:
        return self._request("GET", path, None, token)

    def post(self, path: str, body: dict | None = None, token: str | None = None) -> ApiResult:
        return self._request("POST", path, body if body is not None else {}, token)

    def put(self, path: str, body: dict | None = None) -> ApiResult:
        return self._request("PUT", path, body if body is not None else {})

    def patch(self, path: str, body: dict | None = None) -> ApiResult:
        return self._request("PATCH", path, body if body is not None else {})

    # ---------------------------------------------------------------- auth

    def login_bearer(self, username: str, password: str) -> str:
        """真实登录，mode=bearer，返回 opaque token（同时写入 self.token）。"""
        result = self.post(
            "/api/v1/auth/login",
            {"username": username, "password": password, "mode": "bearer"},
        )
        if result.status != 200 or not isinstance(result.body, dict):
            raise RuntimeError(f"bearer 登录失败: HTTP {result.status} {result.body}")
        token = result.body.get("access_token")
        if not token:
            raise RuntimeError(f"bearer 登录未返回 access_token: {result.body}")
        self.token = token
        return token

    def login_browser(self, username: str, password: str) -> None:
        """真实登录，mode=browser：由 Set-Cookie 建立 pp_session（HttpOnly）。"""
        result = self.post(
            "/api/v1/auth/login",
            {"username": username, "password": password, "mode": "browser"},
        )
        if result.status != 200:
            raise RuntimeError(f"browser 登录失败: HTTP {result.status} {result.body}")
        if self.jar is None or not any(c.name == "pp_session" for c in self.jar):
            raise RuntimeError("browser 登录未建立 pp_session Cookie")

    def session_cookie(self) -> str | None:
        if self.jar is None:
            return None
        for cookie in self.jar:
            if cookie.name == "pp_session":
                return cookie.value
        return None

    def me(self) -> ApiResult:
        return self.get("/api/v1/auth/me")

    def logout(self) -> ApiResult:
        return self.post("/api/v1/auth/logout")


def ensure_system_admin(base_url: str) -> str:
    """真实 Bootstrap 出一个 SYSTEM_ADMIN，并返回它的 bearer token。

    Bootstrap 写入口只允许服务器本机 socket 调用（非本机 404），
    因此本函数只能在**运行后端的同一台机器**上执行。
    """
    client = AuthClient(base_url)
    status = client.get("/api/v1/system/bootstrap/status")
    if status.status != 200 or not isinstance(status.body, dict):
        raise RuntimeError(f"读取 bootstrap 状态失败: HTTP {status.status} {status.body}")

    state = status.body.get("status")
    if state == "NEEDS_INITIALIZATION":
        created = client.post(
            "/api/v1/system/bootstrap",
            {
                "username": BOOTSTRAP_USERNAME,
                "display_name": "D3 验收管理员",
                "password": BOOTSTRAP_PASSWORD,
            },
        )
        if created.status not in (200, 201):
            raise RuntimeError(f"bootstrap 失败: HTTP {created.status} {created.body}")
    elif state == "RECOVERY_REQUIRED":
        raise RuntimeError("数据库处于 RECOVERY_REQUIRED，无法在验收中建立管理员")
    elif state != "READY":
        raise RuntimeError(f"未知 bootstrap 状态: {state!r}")

    return client.login_bearer(BOOTSTRAP_USERNAME, BOOTSTRAP_PASSWORD)


def create_event_admin(
    base_url: str, admin_token: str, username: str, password: str, display_name: str
) -> None:
    """用真实 `POST /api/v1/system/users` 创建 EVENT_ADMIN（幂等：已存在则跳过）。"""
    client = AuthClient(base_url, token=admin_token)
    created = client.post(
        "/api/v1/system/users",
        {
            "username": username,
            "display_name": display_name,
            "password": password,
        },
    )
    if created.status in (200, 201):
        return
    message = created.detail_message or ""
    if created.status in (409, 422) and ("已存在" in message or "exist" in message.lower()):
        return
    raise RuntimeError(f"创建 EVENT_ADMIN 失败: HTTP {created.status} {created.body}")


def provision_event_admin(base_url: str, username: str, password: str, display_name: str) -> AuthClient:
    """Bootstrap + 建号 + bearer 登录，返回可直接调用业务接口的客户端。"""
    admin_token = ensure_system_admin(base_url)
    create_event_admin(base_url, admin_token, username, password, display_name)
    client = AuthClient(base_url)
    client.login_bearer(username, password)
    return client
