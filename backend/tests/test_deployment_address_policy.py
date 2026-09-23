"""D 轨 Day4D：production frontend runtime 不得把部署环境写进业务代码。

## 这条测试到底保护什么（PR #50 review 后收窄）

比赛现场拓扑是「普通无线路由器（AP + switch + router）→ 赛事服务器电脑 → 5–6 台手机」，
示例网段 ``192.168.50.0/24``；未来同一套代码还要直接搬到云服务器与正式域名
（``https://pingpong.example.com``）。要做到“换环境不改业务代码”，需要两条彼此独立的保证：

1. **API transport 必须同源相对**：前端只用 ``/api/...``，绝不用
   ``http://localhost:8000/api/...`` / ``http://192.168.x.x:8000/api/...`` / 固定公网域名。
   由 :func:`test_frontend_api_client_uses_same_origin_relative_paths` 精确保证。
2. **不得把本机 / LAN 环境硬编码进 runtime source**：``127.x``、``localhost``、
   ``192.168.x.x``、``10.x.x.x``、``172.16-31.x.x`` 通常确实意味着有人把现场环境写进了 bundle。
   由 :func:`test_frontend_runtime_has_no_hardcoded_deployment_host` 保证。

## 为什么**不再**全局禁止 ``https?://`` 与 ``:8000``

上一版把 ``https?://`` 与 ``:8000`` 一律列为禁止项，范围过宽：合法外部链接
（帮助文档、隐私政策、外部官网，以及将来 OAuth 的跳转地址）都会被误伤，
而它们与“部署耦合”无关。reviewer 指出这一点后，本条策略收窄为
「**部署环境地址**（回环 / RFC1918）」+「**API 必须同源**」两条精确规则。

``:8000`` 也不再全局禁止：它只在“固定部署主机 + 端口”的组合下才有害，
而那个组合已由第 1 条（``/api/...`` 相对路径）直接排除。

## 扫描范围

``frontend/src`` 下的**运行时源码**（``.ts`` / ``.tsx`` / ``.css``），Python 侧脚本、
``start_pingpong.ps1``、文档里的示例地址都不受影响。

``__tests__`` 目录被排除：测试夹具里出现 ``http://`` 属于合法的测试数据，
且不会被打进 production bundle（``pnpm build`` 只从 ``main.tsx`` 出发打包）。

## 边界

本测试只做**静态文本检查**，不启动服务、不访问网络，也不判断“哪个地址才是对的”。
真正的现场地址由 ``start_pingpong.ps1`` 在启动时**发现并打印**，绝不写入代码。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

#: 会被打进 production bundle 的源码扩展名
_SCANNED_SUFFIXES = (".ts", ".tsx", ".css")

#: 禁止出现在前端运行时源码里的**部署环境地址**（回环 + RFC1918 私网段）。
#:
#: 刻意不含 ``https?://`` 与 ``:8000``：它们本身不等于部署耦合，
#: 全局禁止会误伤合法的外部链接（见模块 docstring）。
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("回环地址 127.x", re.compile(r"\b127\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("localhost", re.compile(r"\blocalhost\b", re.IGNORECASE)),
    ("192.168 私网段", re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")),
    ("10.x 私网段", re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("172.16-31 私网段", re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b")),
)


def _runtime_source_files() -> list[Path]:
    """运行时会进 bundle 的前端源码文件（排除 ``__tests__``）。"""
    files: list[Path] = []
    for path in sorted(FRONTEND_SRC.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _SCANNED_SUFFIXES:
            continue
        if "__tests__" in path.relative_to(FRONTEND_SRC).parts:
            continue
        files.append(path)
    return files


def test_frontend_runtime_has_no_hardcoded_deployment_host() -> None:
    """前端运行时源码里不得出现回环 / RFC1918 部署地址。"""
    files = _runtime_source_files()
    # 防御性断言：真扫到文件才算这条测试有效（目录被改名 / 移走时应立刻失败）
    assert files, f"未在 {FRONTEND_SRC} 找到任何前端运行时源码，扫描范围可能已失效"

    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for label, pattern in _FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_no} 命中「{label}」-> {match.group(0)}"
                )

    assert not violations, (
        "production frontend runtime 不得依赖固定部署地址（否则无法从 LAN 平滑切到云服务器 / 公网域名）：\n"
        + "\n".join(violations)
    )


def test_frontend_api_client_uses_same_origin_relative_paths() -> None:
    """``api.ts`` 的每个请求路径都必须是同源相对路径（``/api/...``）。

    这是「部署可迁移」的**核心保护**：只要 API transport 是同源相对路径，
    LAN、云服务器 IP、正式域名三种部署就天然共用同一份 production build。

    它同时覆盖了“把 base URL 拼在别处”的绕过方式：
    路径字面量直接从 ``request(...)`` / ``submitScore(...)`` 的实参里取，
    因此 ``http://localhost:8000/api/...``、``http://192.168.x.x:8000/api/...``、
    ``https://example.com/api/...`` 都会在这里被抓住。
    """
    api_file = FRONTEND_SRC / "api.ts"
    assert api_file.is_file(), f"未找到 API 客户端：{api_file}"
    text = api_file.read_text(encoding="utf-8")

    # `request<DTO>('/api/...')` 与 `submitScore('/api/...')` 两种写法
    path_literals = re.findall(r"(?:request<[^>]*>|submitScore)\(\s*[`'\"]([^`'\"]+)[`'\"]", text)
    assert path_literals, "未从 api.ts 解析出任何请求路径，断言失效（写法可能已变化）"

    bad = [p for p in path_literals if not p.startswith("/api/")]
    assert not bad, f"以下 API 路径不是同源相对路径 /api/...：{bad}"


def test_frontend_api_transport_is_never_absolute() -> None:
    """``api.ts``（transport 层）不得出现任何绝对 URL。

    比上一条更粗，但覆盖“路径字面量之外”的写法：
    例如 ``const BASE = 'https://example.com'`` 后再拼接。

    注意作用域只限 ``api.ts``：业务页面里合法外部链接（帮助 / 隐私政策 / 官网，
    以及将来 OAuth 跳转地址）**允许**存在，不再被全局禁止。
    """
    api_file = FRONTEND_SRC / "api.ts"
    text = api_file.read_text(encoding="utf-8")

    violations: list[str] = []
    for match in re.finditer(r"https?://", text, re.IGNORECASE):
        line_no = text.count("\n", 0, match.start()) + 1
        violations.append(f"api.ts:{line_no}")

    assert not violations, (
        "API transport 不得绑定任何绝对 URL（部署必须只依赖同源相对路径）："
        f"{violations}"
    )


def test_frontend_dist_is_not_required_by_source_tree() -> None:
    """源码树不得依赖 ``frontend/dist`` 里的具体文件名。

    托管层（``backend/app/static_hosting.py``）按目录动态解析构建产物，
    前端源码里出现 ``index-<hash>.js`` 这类文件名就等于把某一次构建固化进代码。
    """
    offenders: list[str] = []
    pattern = re.compile(r"assets/[A-Za-z0-9_-]+-[A-Za-z0-9_]{8}\.(?:js|css)")
    for path in _runtime_source_files():
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no} -> {match.group(0)}")
    assert not offenders, f"前端源码引用了带 hash 的构建产物文件名：{offenders}"
