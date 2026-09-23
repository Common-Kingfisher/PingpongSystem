"""D 轨 Day4D（PR #50 review rework）：启动脚本关键契约的静态回归。

## 为什么用静态断言

本机没有 Pester，reviewer 也明确要求「不要为了这一条修复引入新的 PowerShell 测试框架」。
因此这里用 **读文件 + 关键结构断言** 的方式，锁住 ``start_pingpong.ps1`` 里那些
“写错了也不会报错、但会静默给出错误结果”的语义：

1. **数据库路径解析基准**：相对 ``PINGPONG_DB_PATH`` / ``DEMO_DB_PATH`` 必须相对
   ``backend/`` 解析（= 后端 CWD），与 ``backend/app/db.py::_db_path()`` 的
   ``Path(override)`` 语义一致；
2. **probe 只消费 PowerShell 规范化的绝对路径 argv**，不再读环境变量
   —— 否则进程里的原始相对 env 会覆盖 argv，修复失效；
3. **probe 保持只读**：``mode=ro``，不含任何写 / DDL 语句；
4. **UTF-8 BOM 必须保留**：本机 ``pwsh`` 实为 PowerShell 5.1，会把无 BOM 的 ``.ps1``
   按 ANSI 读取，中文提示会乱码甚至触发伪语法错误；
5. **脚本永不修改防火墙 / 网卡 / 路由器**：只允许检测与提示；
6. **Day4D 既有能力不退化**：多网卡降权（而非删除）、多地址提示、深链接 smoke、
   防火墙只读、``-TournamentId`` 显式覆盖、无赛事时降级到 base URL。

静态断言不能替代行为验证，因此同轮还真实执行了「4 个数据库路径场景 × 跨目录启动」
的 smoke（结果记录在 ``docs/WORKSTREAM_D.md`` 的「D 轨 Day4D · PR #50 Review Rework」
章节，第 34 节；仓库中没有也不需要单独的 rework 文档）。
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "start_pingpong.ps1"


def _script_text() -> str:
    assert SCRIPT.is_file(), f"未找到启动脚本：{SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def _probe_code() -> str:
    """取出 ``$probeCode = @' ... '@`` 这段 Python here-string 的正文。"""
    text = _script_text()
    match = re.search(r"\$probeCode = @'\r?\n(?P<code>.*?)\r?\n'@", text, re.DOTALL)
    assert match, "未能从 start_pingpong.ps1 提取 probe here-string，脚本结构可能已变化"
    return match.group("code")


# --------------------------------------------------------------- 1. 路径解析基准


def test_relative_db_override_resolves_against_backend() -> None:
    """相对 override 必须以 ``$backend`` 为基准，且最终规范化为绝对路径。"""
    text = _script_text()

    rooted_marker = "[System.IO.Path]::IsPathRooted($dbPath)"
    full_marker = "[System.IO.Path]::GetFullPath($dbPath)"
    assert rooted_marker in text, "必须显式判断 override 是否为绝对路径"
    assert full_marker in text, "传给 probe 之前必须规范化为绝对路径"

    rooted_at = text.index(rooted_marker)
    full_at = text.index(full_marker)
    assert rooted_at < full_at, "应先判断 rooted，再统一 GetFullPath"

    region = text[rooted_at:full_at]
    assert "Join-Path $backend" in region, (
        "相对 override 必须相对 $backend（= 后端 CWD）拼接；"
        "相对 $root 或调用方 CWD 会读到另一份 SQLite，打印出指向错误赛事的链接"
    )
    assert "Join-Path $root" not in region, "不得以 $root 作为相对 override 的基准"


def test_db_path_priority_matches_backend() -> None:
    """优先级必须与 ``db.py::_db_path()`` 一致：PINGPONG_DB_PATH > DEMO_DB_PATH > 默认。"""
    text = _script_text()
    p = text.index("$dbPath = $env:PINGPONG_DB_PATH")
    d = text.index("$dbPath = $env:DEMO_DB_PATH")
    default = text.index("Join-Path $backend 'data\\demo.db'")
    assert p < d < default, "覆盖变量优先级与默认路径顺序必须与后端一致"


def test_probe_file_is_deleted_after_use() -> None:
    """临时 probe 文件必须在 finally 中清理，且失败也不阻断启动。"""
    text = _script_text()
    assert "Remove-Item -LiteralPath $probeFile" in text
    assert "} finally {" in text


# --------------------------------------------------------------- 2/3. probe 契约


def test_probe_consumes_normalized_absolute_path_only() -> None:
    """probe 只能使用 ``sys.argv[1]``，不得再读 ``PINGPONG_DB_PATH`` / ``DEMO_DB_PATH``。"""
    code = _probe_code()

    assert "db = sys.argv[1]" in code, "probe 必须以 argv 为准"
    assert "os.environ" not in code, (
        "probe 不得读环境变量：原始相对 env 会覆盖已规范化的 argv，使 P1 修复失效"
    )
    for env_name in ("PINGPONG_DB_PATH", "DEMO_DB_PATH"):
        assert env_name not in code, f"probe 不得引用 {env_name}"


def test_probe_is_strictly_read_only() -> None:
    """probe 只读打开，且不含任何写 / DDL 语句。"""
    code = _probe_code()

    assert "mode=ro" in code, "probe 必须只读打开数据库"
    assert "SELECT id FROM tournaments" in code

    upper = code.upper()
    for keyword in (
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "DROP",
        "ALTER",
        "ATTACH",
        "REPLACE INTO",
        "PRAGMA",
    ):
        assert keyword not in upper, f"probe 不得包含写 / DDL 语句：{keyword}"


# --------------------------------------------------------------- 4. 编码


def test_script_keeps_utf8_bom() -> None:
    """``start_pingpong.ps1`` 必须保留 UTF-8 BOM（PowerShell 5.1 的 ANSI 解析坑）。"""
    raw = SCRIPT.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8), (
        "start_pingpong.ps1 丢失了 UTF-8 BOM：PowerShell 5.1 会把无 BOM 脚本按 ANSI 读取，"
        "中文提示会乱码甚至触发伪语法错误（见 docs/WORKSTREAM_D.md §17.4）"
    )


# --------------------------------------------------------------- 5. 只检测不修改


def test_script_never_modifies_firewall_or_network() -> None:
    """脚本只能检测 / 提示，绝不允许新增、修改、删除防火墙规则或网卡配置。"""
    text = _script_text()

    forbidden = (
        "New-NetFirewallRule",
        "Set-NetFirewallRule",
        "Remove-NetFirewallRule",
        "Set-NetFirewallProfile",
        "Disable-NetFirewallProfile",
        "netsh advfirewall set",
        "New-NetIPAddress",
        "Set-NetIPAddress",
        "Remove-NetIPAddress",
        "Set-NetConnectionProfile",
        "netsh interface ip set",
        "route add",
    )
    hits = [cmdlet for cmdlet in forbidden if cmdlet in text]
    assert not hits, f"启动脚本不得修改系统网络 / 防火墙配置，但出现了：{hits}"


# --------------------------------------------------------------- 6. 既有能力


def test_day4d_lan_capabilities_are_preserved() -> None:
    """Day4D 的 LAN 能力不得在后续改动中回退。"""
    text = _script_text()

    markers = {
        "虚拟网卡识别函数": "Test-VirtualAdapterName",
        "多地址提示": "检测到多个局域网地址",
        "防火墙只读检测": "Get-NetFirewallProfile",
        "TournamentId 参数": "[int]$TournamentId = 0",
        "无赛事降级文案": "尚未读到赛事 id",
        "Public 深链接示例": "/public/t/",
        "SPA 探测标记": 'id="root"',
        "启动横幅": "PingpongSystem 已启动",
        "仅排序不删除": "Sort-Object Rank",
        "逐个展示全部候选地址": "foreach ($item in $lanIps)",
    }
    missing = [label for label, marker in markers.items() if marker not in text]
    assert not missing, f"以下 Day4D 能力疑似被回退：{missing}"
