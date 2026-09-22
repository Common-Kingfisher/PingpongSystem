"""D 轨 Day 2：production 单服务静态托管与 SPA fallback 安全测试。

覆盖目标（对应 D Day 2 验收项）：

1. ``/api/health`` 仍返回 JSON；
2. ``/api/*`` 未知路径保持 API 语义 404，不被 SPA fallback 吞掉；
3. ``frontend/dist`` 存在时 ``/`` 返回前端入口；
4. 深链接（如 ``/public/t/1/live``）返回 SPA，刷新不 404；
5. ``/assets/*`` 与 dist 根下的真实静态文件可正常访问；
6. ``frontend/dist`` 不存在时退化为 API-only 模式，不 crash；
7. POST/PUT 等写请求不会被 fallback 成 HTML；
8. 路径穿越（``../``）不能逃出 dist。

所有用例都使用 ``tmp_path`` 构造 dist，不依赖开发者机器的绝对路径。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as default_app
from app.static_hosting import DEFAULT_DIST_DIR, install_static_hosting, resolve_dist_file

SPA_SHELL = "<!doctype html><html><body><div id=\"root\"></div></body></html>"


def _make_dist(root: Path) -> Path:
    """构造一个最小可用的 Vite 构建产物目录。"""
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(SPA_SHELL, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log('spa')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


@pytest.fixture()
def hosted_app(tmp_path):
    """带假 dist 的独立 FastAPI 应用（不含业务 router，只验证托管与 fallback 行为）。"""
    dist = _make_dist(tmp_path)
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    enabled = install_static_hosting(app, dist)
    assert enabled is True
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def api_only_app(tmp_path):
    """dist 不存在时的 API-only 应用。"""
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    enabled = install_static_hosting(app, tmp_path / "missing-dist")
    assert enabled is False
    with TestClient(app) as client:
        yield client


# ------------------------------------------------------------------ 1. API 语义不受影响


def test_health_still_returns_json(hosted_app):
    resp = hosted_app.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["content-type"].startswith("application/json")


def test_unknown_api_path_is_not_swallowed_by_spa_fallback(hosted_app):
    resp = hosted_app.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == "Not Found"


def test_catch_all_does_not_match_api_paths_at_all(tmp_path):
    """回归护栏：catch-all 必须在**路径匹配阶段**就放掉 ``/api/*``。

    若 catch-all 命中了 ``/api/*``，Starlette 会因“路径匹配、方法不匹配”返回
    **405**，把本来不存在的 API 端点从 404 变成 405，破坏既有 API 语义
    （``test_team_runtime`` 依赖该 404 证明“不存在直接改对抗比分的接口”）。
    返回 ``Match.NONE`` 才能让它继续走到默认 404。
    """
    from starlette.routing import Match

    app = FastAPI()
    assert install_static_hosting(app, _make_dist(tmp_path)) is True
    catch_all = next(
        route for route in app.routes if getattr(route, "name", None) == "spa-fallback"
    )
    api_scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/tournaments/1/team-ties/1/score",
        "root_path": "",
        "headers": [],
    }
    match, _ = catch_all.matches(api_scope)
    assert match is Match.NONE

    page_scope = {**api_scope, "method": "GET", "path": "/public/t/1/live"}
    match, _ = catch_all.matches(page_scope)
    assert match is not Match.NONE


def test_bare_api_prefix_is_not_swallowed(hosted_app):
    resp = hosted_app.get("/api")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_reserved_docs_paths_are_reachable_and_not_html_404(hosted_app):
    """独立 app 自带 FastAPI docs，这些路径必须由 FastAPI 正常响应，而不是落到 SPA。"""
    for path in ("/openapi.json", "/docs", "/redoc"):
        resp = hosted_app.get(path)
        assert resp.status_code == 200, path
    assert hosted_app.get("/openapi.json").headers["content-type"].startswith("application/json")


def test_reserved_docs_paths_are_reserved_when_docs_disabled(tmp_path):
    """即便 docs 被显式关闭（doc_url=None），这些路径也不能退化成 HTML。"""
    dist = _make_dist(tmp_path)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    assert install_static_hosting(app, dist) is True
    with TestClient(app) as client:
        for path in ("/openapi.json", "/docs", "/redoc"):
            resp = client.get(path)
            assert resp.status_code == 404, path
            assert resp.headers["content-type"].startswith("application/json"), path


# ------------------------------------------------------------------ 2. 前端入口与深链接


def test_root_serves_spa_shell(hosted_app):
    resp = hosted_app.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert 'id="root"' in resp.text
    assert "no-cache" in resp.headers.get("cache-control", "")


@pytest.mark.parametrize(
    "path",
    ["/public/t/1/live", "/public/t/12/schedule", "/public/t/12/register", "/console", "/orderbook"],
)
def test_deep_links_serve_spa_shell(hosted_app, path):
    """BrowserRouter 深链接刷新必须拿到 index.html，而不是 404。"""
    resp = hosted_app.get(path)
    assert resp.status_code == 200, path
    assert 'id="root"' in resp.text, path


def test_deep_link_head_request_is_supported(hosted_app):
    """HEAD 与 GET 一样属于合理的前端读取请求（预检/探测不应 404）。"""
    resp = hosted_app.head("/public/t/12/live")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_exact_api_slash_is_not_swallowed(hosted_app):
    resp = hosted_app.get("/api/")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_assets_are_served_with_correct_mime(hosted_app):
    resp = hosted_app.get("/assets/index-abc123.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('spa')"
    assert "javascript" in resp.headers["content-type"]


def test_root_level_static_file_is_served_from_dist(hosted_app):
    resp = hosted_app.get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.text == "<svg/>"


def test_missing_asset_is_404_and_never_html(hosted_app):
    """缺失的构建资源必须是 404 —— 返回一份 index.html 只会让浏览器报 MIME 错误。"""
    resp = hosted_app.get("/assets/does-not-exist.js")
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")


# ------------------------------------------------------------------ 3. 写请求不被包装成 HTML


def test_post_to_frontend_path_is_not_fallback_html(hosted_app):
    resp = hosted_app.post("/public/t/1/live")
    assert resp.status_code == 405
    assert "text/html" not in resp.headers.get("content-type", "")


def test_put_to_unknown_api_path_stays_api_semantics(hosted_app):
    """写请求落在 /api/* 上时必须是 JSON 4xx，绝不能被包装成 HTML。"""
    resp = hosted_app.put("/api/does-not-exist", json={})
    assert resp.status_code in (404, 405)
    assert resp.headers["content-type"].startswith("application/json")
    assert "text/html" not in resp.headers["content-type"]


# ------------------------------------------------------------------ 4. dist 缺失 -> API-only


def test_api_only_mode_health_works(api_only_app):
    resp = api_only_app.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_api_only_mode_frontend_path_returns_404(api_only_app):
    """没有 dist 时不应凭空返回 HTML，也不应 crash。"""
    resp = api_only_app.get("/public/t/1/live")
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")


def test_install_returns_false_when_dist_missing(tmp_path):
    app = FastAPI()
    assert install_static_hosting(app, tmp_path / "nope") is False


def test_default_dist_dir_points_at_frontend_dist():
    assert DEFAULT_DIST_DIR.name == "dist"
    assert DEFAULT_DIST_DIR.parent.name == "frontend"


# ------------------------------------------------------------------ 5. 路径穿越防护


@pytest.mark.parametrize(
    "raw",
    ["", "/", "../secret.txt", "assets/../../secret.txt", "..\\secret.txt", "assets"],
)
def test_resolve_dist_file_rejects_non_file_targets(tmp_path, raw):
    dist = _make_dist(tmp_path)
    (tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")
    assert resolve_dist_file(dist, raw) is None


def test_resolve_dist_file_accepts_real_file(tmp_path):
    dist = _make_dist(tmp_path)
    resolved = resolve_dist_file(dist, "/assets/index-abc123.js")
    assert resolved is not None
    assert resolved.read_text(encoding="utf-8") == "console.log('spa')"


def test_traversal_request_cannot_escape_dist(hosted_app, tmp_path):
    """真实 HTTP 请求也不能读到 dist 之外的文件。"""
    resp = hosted_app.get("/../secret.txt")
    assert "top-secret" not in resp.text


# ------------------------------------------------------------------ 6. 真实 app 的托管状态


class TestRealAppStaticHosting:
    """对真实 ``app.main:app`` 的断言。

    这些用例断言的是“真实 app 与当前仓库 dist 状态一致”：

    * dist 存在 -> 单服务托管生效；
    * dist 不存在（开发者未执行 pnpm build）-> API-only，且 API 不受影响。
    """

    @pytest.fixture()
    def client(self):
        with TestClient(default_app) as c:
            yield c

    def test_health_ok_regardless_of_dist(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_unknown_api_path_is_api_404(self, client):
        resp = client.get("/api/does-not-exist")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")

    def test_docs_routes_are_not_shadowed_by_spa(self, client):
        """FastAPI 自带 OpenAPI / Swagger 不能被 catch-all 覆盖。"""
        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert openapi.headers["content-type"].startswith("application/json")
        assert "paths" in openapi.json()

        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "text/html" in docs.headers["content-type"]

    def test_frontend_served_only_when_dist_exists(self, client):
        resp = client.get("/")
        if (DEFAULT_DIST_DIR / "index.html").is_file():
            assert resp.status_code == 200
            assert 'id="root"' in resp.text
        else:
            # 开发环境尚未 pnpm build：保持 API-only，不应 crash
            assert resp.status_code == 404

    def test_deep_link_behaviour_matches_dist_presence(self, client):
        resp = client.get("/public/t/1/live")
        if (DEFAULT_DIST_DIR / "index.html").is_file():
            assert resp.status_code == 200
            assert 'id="root"' in resp.text
        else:
            assert resp.status_code == 404
