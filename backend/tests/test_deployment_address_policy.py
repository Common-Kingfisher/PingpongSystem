"""D 轨 Day 4D：production frontend runtime 不得依赖任何固定网络地址。

## 为什么需要这条测试

比赛现场拓扑是「普通无线路由器（AP + switch + router）→ 赛事服务器电脑 → 5–6 台手机」，
示例网段 ``192.168.50.0/24``；未来同一套代码还要直接搬到云服务器与正式域名
（``https://pingpong.example.com``）。要做到“换环境不改业务代码”，
唯一可靠的做法是前端运行时**只用同源相对路径**（``/api/...``）：

* 局域网：``http://192.168.50.10:8000``    → ``fetch('/api/health')`` → 同源
* 云服务器：``http://<云 IP>:8000``         → 同一份 bundle 仍成立
* 正式域名：``https://pingpong.example.com`` → 同一份 bundle 仍成立

因此 ``frontend/src`` 里一旦出现 ``127.0.0.1`` / ``localhost`` / 私网段 / 写死端口 /
``http(s)://`` 绝对地址，就说明有人把部署环境写进了业务代码，本测试直接失败。

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

#: 不允许出现在前端运行时源码里的固定地址 / 端口
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("回环地址 127.x", re.compile(r"\b127\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("localhost", re.compile(r"\blocalhost\b", re.IGNORECASE)),
    ("192.168 私网段", re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")),
    ("10.x 私网段", re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("172.16-31 私网段", re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b")),
    ("写死端口 :8000", re.compile(r":8000\b")),
    ("绝对 http(s) 地址", re.compile(r"https?://", re.IGNORECASE)),
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


def test_frontend_runtime_has_no_hardcoded_network_address() -> None:
    """前端运行时源码里不得出现任何固定地址 / 写死端口。"""
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
        "production frontend runtime 不得依赖固定网络地址（否则无法从 LAN 平滑切到云服务器 / 公网域名）：\n"
        + "\n".join(violations)
    )


def test_frontend_api_client_uses_same_origin_relative_paths() -> None:
    """``api.ts`` 的每个请求路径都必须是同源相对路径（``/api/...``）。

    这条断言比上面的文本扫描更精确：它直接检查 API 客户端**实际传入 fetch 的路径字面量**，
    避免“把 base URL 拼在别处”这种绕过方式（例如 ``const BASE = 'http://x'`` 后再拼接）。
    """
    api_file = FRONTEND_SRC / "api.ts"
    assert api_file.is_file(), f"未找到 API 客户端：{api_file}"
    text = api_file.read_text(encoding="utf-8")

    # `request<DTO>('/api/...')` 与 `submitScore('/api/...')` 两种写法
    path_literals = re.findall(r"(?:request<[^>]*>|submitScore)\(\s*[`'\"]([^`'\"]+)[`'\"]", text)
    assert path_literals, "未从 api.ts 解析出任何请求路径，断言失效（写法可能已变化）"

    bad = [p for p in path_literals if not p.startswith("/api/")]
    assert not bad, f"以下 API 路径不是同源相对路径 /api/...：{bad}"


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
