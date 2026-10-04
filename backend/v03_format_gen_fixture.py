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

用法：

```powershell
cd backend
.\.venv\Scripts\python.exe .\v03_format_gen_fixture.py [base_url]
```

输出（供 `v03_format_gen_browser_check.mjs` 消费）：

```text
LOGIN_USERNAME=...
LOGIN_PASSWORD=...
TID_ROUND_ROBIN=...
TID_SINGLE_ELIMINATION=...
TID_GROUP_KNOCKOUT=...
```
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

USERNAME = "v03-format-admin"
PASSWORD = "v03-format-pass1"
DISPLAY_NAME = "V0.3 赛制生成验收管理员"

#: (format_code, 赛事名, 人数, 组数, 每组出线, 球台数)
CASES = (
    ("ROUND_ROBIN", "V0.3 验收 A · 单循环（6 人）", 6, 1, 2, 3),
    ("SINGLE_ELIMINATION", "V0.3 验收 B · 单淘汰（6 人）", 6, 1, 2, 3),
    ("GROUP_KNOCKOUT", "V0.3 验收 C · 小组淘汰（8 人 2 组）", 8, 2, 2, 4),
)


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
    client = provision_event_admin(BASE, USERNAME, PASSWORD, DISPLAY_NAME)
    print(f"LOGIN_USERNAME={USERNAME}")
    print(f"LOGIN_PASSWORD={PASSWORD}")

    for format_code, name, players, groups, qualify, tables in CASES:
        tid = _create_case(client, format_code, name, players, groups, qualify, tables)
        print(f"TID_{format_code}={tid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
