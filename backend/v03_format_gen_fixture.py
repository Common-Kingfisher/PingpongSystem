"""V0.3 三赛制生成链路：浏览器验收 fixture。

创建三个**全新**赛事，全部停在"可以在 Draw 页面真实点击生成按钮"的状态：

```text
A. ROUND_ROBIN         6 人 / 1 组 / 3 台  → 名单已确认，等待生成循环赛
B. SINGLE_ELIMINATION  6 人 / 1 组 / 3 台  → 名单已确认，等待生成单淘汰签
C. GROUP_KNOCKOUT      8 人 / 2 组 / 4 台  → 名单已确认，等待生成分组 + 小组比赛
```

## 边界

- 全程走**真实 HTTP 契约**（bootstrap → EVENT_ADMIN → bearer），没有任何直接写库；
- 刻意**不**预先生成分组或比赛，也**不**预设种子：这些真实点击留给浏览器验收，
  否则验收就变成"验证 fixture 而不是验证产品入口"；
- `SINGLE_ELIMINATION` 取 6 人（非 2 幂），让浏览器链同时覆盖 BYE / WALKOVER；
- 三个赛事都不开启公开报名，避免与 D 轨报名语义混淆。

## fixture 隔离（PR #68 review Finding #4）

旧版本有三处会让"重复执行"污染结论：

1. 账号口令硬编码在源码里、并被 checker 当默认值使用；
2. 每轮都建**同名**赛事；
3. checker 靠"赛事名包含某个标记"扫描列表，重复执行时可能命中**上一轮**的旧赛事。

现在：

- 口令只能来自环境变量 ``PINGPONG_E2E_ADMIN_PASSWORD``，缺失或过短一律 **fail closed**
  （退出码 2），不再提供任何默认口令；
- 每轮生成唯一 ``RUN_ID``（UTC 时间戳 + 短随机后缀），账号名与三个赛事名都带它；
- 输出一份 JSON 交接文件，checker **直接消费其中的 tid**，不再扫描赛事列表。

用法：

```powershell
cd backend
$env:PINGPONG_E2E_ADMIN_PASSWORD = "<至少 12 位的测试口令>"
.\.venv\Scripts\python.exe .\v03_format_gen_fixture.py [base_url] [fixture_json_path]
```

输出（stdout，供人工/脚本读取）：

```text
RUN_ID=...
LOGIN_USERNAME=...
FIXTURE_JSON=<path>
TID_ROUND_ROBIN=...
TID_SINGLE_ELIMINATION=...
TID_GROUP_KNOCKOUT=...
```

``FIXTURE_JSON``（默认写入系统临时目录，不落进仓库）结构：

```json
{
  "run_id": "...",
  "base_url": "http://127.0.0.1:8099",
  "username": "v03-format-<run_id>",
  "password_env": "PINGPONG_E2E_ADMIN_PASSWORD",
  "tids": {"ROUND_ROBIN": 1, "SINGLE_ELIMINATION": 2, "GROUP_KNOCKOUT": 3},
  "names": {"ROUND_ROBIN": "...", ...},
  "created_at": "2026-10-05T02:15:30+00:00"
}
```
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))

from day3_auth_client import AuthClient, provision_event_admin  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

#: 口令**只能**来自环境变量：缺失即 fail closed，不提供任何默认值。
PASSWORD_ENV = "PINGPONG_E2E_ADMIN_PASSWORD"
#: 口令最短长度与后端 ``BootstrapRequest.password`` (min_length=12) 对齐。
MIN_PASSWORD_LENGTH = 12

#: 每轮唯一运行标识：UTC 时间戳 + 短随机后缀。
RUN_ID = os.environ.get("PINGPONG_E2E_RUN_ID") or (
    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
)
USERNAME = f"v03-format-{RUN_ID}"
DISPLAY_NAME = f"V0.3 赛制生成验收管理员 {RUN_ID}"

#: (format_code, 赛事名模板, 人数, 组数, 每组出线, 球台数)
CASES = (
    ("ROUND_ROBIN", "V0.3 验收 A · 单循环（6 人）· {run_id}", 6, 1, 2, 3),
    ("SINGLE_ELIMINATION", "V0.3 验收 B · 单淘汰（6 人）· {run_id}", 6, 1, 2, 3),
    ("GROUP_KNOCKOUT", "V0.3 验收 C · 小组淘汰（8 人 2 组）· {run_id}", 8, 2, 2, 4),
)


def _password() -> str:
    """从环境变量取验收口令；缺失/过短一律 fail closed。"""
    value = os.environ.get(PASSWORD_ENV, "")
    if not value:
        print(
            f"FAIL: 必须设置环境变量 {PASSWORD_ENV}（至少 {MIN_PASSWORD_LENGTH} 位）。"
            "fixture 不再提供任何硬编码默认口令。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if len(value) < MIN_PASSWORD_LENGTH:
        print(
            f"FAIL: {PASSWORD_ENV} 至少 {MIN_PASSWORD_LENGTH} 位（后端 BootstrapRequest 约束）。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return value


def _fixture_path() -> Path:
    if len(sys.argv) > 2:
        return Path(sys.argv[2])
    override = os.environ.get("PINGPONG_E2E_FIXTURE")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / f"v03_format_gen_fixture_{RUN_ID}.json"


def _create_case(client: AuthClient, format_code: str, name: str, players: int,
                 groups: int, qualify: int, tables: int) -> int:
    created = client.post(
        "/api/tournaments",
        {
            "name": name,
            "date": "2026-10-02",
            "table_count": tables,
            "group_count": groups,
            "qualify_per_group": qualify,
            "event_type": "SINGLES",
            "format_code": format_code,
            "operation_mode": "LIVE",
            "games_to_win": 2,
            "points_to_win": 11,
        },
    )
    if created.status not in (200, 201):
        raise RuntimeError(f"创建赛事失败 ({format_code}): HTTP {created.status} {created.body}")
    tid = created.body["id"]

    for index in range(1, players + 1):
        added = client.post(
            f"/api/tournaments/{tid}/players",
            {"name": f"选手{index:02d}", "college": f"单位{index % 2 + 1}", "rating_points": 1000 + index},
        )
        if added.status not in (200, 201):
            raise RuntimeError(f"添加选手 {index} 失败: HTTP {added.status} {added.body}")

    confirmed = client.post(f"/api/tournaments/{tid}/confirm-roster")
    if confirmed.status != 200:
        raise RuntimeError(f"确认名单失败 ({format_code}): HTTP {confirmed.status} {confirmed.body}")

    tournament = client.get(f"/api/tournaments/{tid}").body
    if tournament["format_code"] != format_code:
        raise RuntimeError(f"{format_code} 未真实落库: {tournament['format_code']!r}")
    if tournament["stage"] != "REGISTRATION":
        raise RuntimeError(f"fixture 应停在 REGISTRATION，实际 {tournament['stage']}")
    if not tournament["roster_confirmed"]:
        raise RuntimeError("名单未确认，Draw 页面不会开放生成入口")
    if client.get(f"/api/tournaments/{tid}/matches").body:
        raise RuntimeError("fixture 不得预生成比赛：真实生成留给浏览器")
    return tid


def main() -> int:
    password = _password()
    client = provision_event_admin(BASE, USERNAME, password, DISPLAY_NAME)

    tids: dict[str, int] = {}
    names: dict[str, str] = {}
    for format_code, name_template, players, groups, qualify, tables in CASES:
        name = name_template.format(run_id=RUN_ID)
        tid = _create_case(client, format_code, name, players, groups, qualify, tables)
        tids[format_code] = tid
        names[format_code] = name

    fixture = {
        "run_id": RUN_ID,
        "base_url": BASE,
        "username": USERNAME,
        "password_env": PASSWORD_ENV,
        "tids": tids,
        "names": names,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _fixture_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"RUN_ID={RUN_ID}")
    print(f"LOGIN_USERNAME={USERNAME}")
    print(f"FIXTURE_JSON={path}")
    for format_code in ("ROUND_ROBIN", "SINGLE_ELIMINATION", "GROUP_KNOCKOUT"):
        print(f"TID_{format_code}={tids[format_code]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
