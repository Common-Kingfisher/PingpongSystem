"""Production 单服务静态托管（D 轨 Day 2）。

目标拓扑：同一个 FastAPI 进程同时对外提供

* ``/api/*``    -> 原有后端 API（本模块不参与）
* ``/assets/*`` -> ``frontend/dist/assets``（Vite 构建产物，带 hash，可长期缓存）
* 其他前端 GET  -> ``frontend/dist/index.html``（SPA fallback，兼容 BrowserRouter 深链接）

三条硬约束：

1. **SPA fallback 必须最后注册**，绝不能吞掉已注册的 API / OpenAPI / docs 路由；
2. **``/api/*`` 永远保持 API 语义**：未知 API 路径必须与“没装托管时”完全一致，
   不能返回 index.html，也不能把 404 变成 405；
3. **``frontend/dist`` 不存在时不影响 API 启动**：此时退化为 API-only 开发模式，
   不注册任何静态路由，也不抛异常。

调用方只需在 ``main.py`` 所有 router 注册完成之后调用一次 :func:`install_static_hosting`。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse, Response
from starlette.routing import Match

logger = logging.getLogger("app")

#: 仓库根目录（backend/app/static_hosting.py -> backend/app -> backend -> 仓库根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 默认前端构建产物目录：``frontend/dist``
DEFAULT_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

#: FastAPI 自带文档路由。这些路径即使被显式关闭，也不能落到 SPA fallback，
#: 否则会返回一份 HTML，掩盖“接口不存在”的事实。
_RESERVED_ROOT_PATHS = frozenset(
    {"docs", "redoc", "openapi.json", "docs/oauth2-redirect", "swagger-ui-bundle.js"}
)


def _is_api_path(path: str) -> bool:
    """``/api`` 与 ``/api/...`` 都属于 API 命名空间，永远不能走 SPA fallback。"""
    return path == "/api" or path.startswith("/api/")


class SpaFallbackRoute(APIRoute):
    """SPA catch-all 路由。

    必须在**路径匹配阶段**就拒绝 ``/api/*``，而不是等到 handler 里再返回 404。

    原因：``/{full_path:path}`` 对任何路径都是 ``Match.PARTIAL``，而 Starlette 只要看到
    “路径匹配、方法不匹配”就返回 **405 Method Not Allowed**。若 catch-all 吞下 ``/api/*``，
    一个**根本不存在**的 API 端点（例如 ``POST /api/tournaments/1/team-ties/1/score``）
    会从 404 变成 405，直接改变既有 API 语义——``test_team_runtime`` 正是依赖该 404
    来证明“不存在直接改对抗比分的接口，避免两个真相源”。

    返回 ``Match.NONE`` 后，Starlette 会继续走到默认 404，与未安装托管时完全一致。
    """

    def matches(self, scope):
        match, child_scope = super().matches(scope)
        if match is not Match.NONE and _is_api_path(scope.get("path", "")):
            return Match.NONE, {}
        return match, child_scope


def _no_cache_headers() -> dict[str, str]:
    """SPA 入口不缓存：否则 ``pnpm build`` 后浏览器仍加载旧 hash 资源，出现白屏。"""
    return {"Cache-Control": "no-cache, must-revalidate"}


def resolve_dist_file(dist_dir: Path, full_path: str) -> Path | None:
    """把 URL 路径安全地解析成 dist 内的真实文件。

    返回 ``None`` 表示“这不是一个真实静态文件”，调用方应回退到 SPA 入口。

    安全语义：

    * 空路径 / ``/``            -> ``None``（交给 SPA 入口）
    * 目录（如 ``assets``）      -> ``None``（目录不直接可访问）
    * 越界路径（``../`` 等）     -> ``None``（不得逃出 dist）
    """
    candidate = (full_path or "").strip().lstrip("/")
    if not candidate:
        return None

    dist_root = dist_dir.resolve()
    resolved = (dist_root / candidate).resolve()

    if not resolved.is_relative_to(dist_root):
        return None
    if not resolved.is_file():
        return None
    return resolved


def build_static_hosting_routes(dist_dir: Path) -> tuple[StaticFiles | None, APIRoute | None]:
    """构造 production 静态托管所需的两个 route。

    ``(assets_route, fallback_route)``：

    * ``assets_route``：``/assets/*`` 的 ``StaticFiles``；``dist/assets`` 缺失时为 ``None``；
    * ``fallback_route``：SPA catch-all；``dist/index.html`` 缺失时为 ``None``。

    与 ``app`` 解耦，便于单测直接检查匹配行为（例如确认 ``/api/*`` 不被 catch-all 命中）。
    """
    target = Path(dist_dir)
    index_file = target / "index.html"
    assets_dir = target / "assets"

    if not index_file.is_file():
        logger.info(
            "frontend/dist 不存在（%s）：以 API-only 开发模式运行，未启用 SPA 静态托管。"
            "生产单服务请在 frontend 目录执行 pnpm build 后重启。",
            target,
        )
        return None, None

    # /assets/* 交给 StaticFiles：自带路径逃逸防护、ETag 与正确的 MIME。
    if assets_dir.is_dir():
        assets_route: StaticFiles | None = StaticFiles(directory=str(assets_dir))
    else:
        assets_route = None
        logger.warning(
            "frontend/dist/assets 缺失（%s）：前端资源将无法加载，建议重新执行 pnpm build。",
            assets_dir,
        )

    def spa_fallback(request: Request) -> Response:
        """未命中任何 API / 静态文件的前端 GET/HEAD 请求，返回 SPA 入口。

        只处理 GET/HEAD：POST/PUT/DELETE 等写请求落在前端路径上时返回 405，
        而不会被包装成 HTML；API 写请求仍由各自的 router 处理。
        """
        full_path = request.path_params.get("full_path", "") or ""

        # 1) 防御性兜底：/api/* 永远保持 API 语义（正常已由 SpaFallbackRoute 排除）
        if _is_api_path(f"/{full_path}") or _is_api_path(full_path):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        # 2) FastAPI 文档路径保持 404，避免“HTML 版 404”掩盖接口不存在
        if full_path in _RESERVED_ROOT_PATHS:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        # 3) 真实静态文件（favicon.svg 等）
        static_file = resolve_dist_file(target, full_path)
        if static_file is not None:
            return FileResponse(static_file)

        # 4) 其余前端路由 -> index.html，交给 React Router 处理
        return HTMLResponse(index_file.read_text(encoding="utf-8"), headers=_no_cache_headers())

    fallback_route = SpaFallbackRoute(
        "/{full_path:path}",
        spa_fallback,
        methods=["GET", "HEAD"],
        include_in_schema=False,
        name="spa-fallback",
    )
    return assets_route, fallback_route


def install_static_hosting(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """在 ``app`` 上安装 production 静态托管，返回是否真的启用。

    ``dist_dir`` 为空时使用 :data:`DEFAULT_DIST_DIR`。

    必须在所有 API router 注册之后调用——本函数会把 catch-all 追加到路由表末尾；
    提前调用会让它排在业务路由之前。
    """
    target = Path(dist_dir) if dist_dir is not None else DEFAULT_DIST_DIR
    assets_route, fallback_route = build_static_hosting_routes(target)
    if fallback_route is None:
        return False

    if assets_route is not None:
        app.mount("/assets", assets_route, name="assets")

    # 直接追加到路由表：api_route 装饰器不支持自定义 route class，
    # 而这里必须用 SpaFallbackRoute 才能在路径匹配阶段排除 /api/*。
    app.router.routes.append(fallback_route)

    logger.info(
        "已启用 production 单服务静态托管：/assets/* -> %s，其余前端 GET -> %s",
        target / "assets",
        target / "index.html",
    )
    return True
