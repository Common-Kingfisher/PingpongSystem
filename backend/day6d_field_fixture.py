"""D 轨 Day6D 现场模拟：E5 全链前置赛事。

与 Day3 验收脚本同样的原则：**没有任何绕过**。
真实 bootstrap → 真实建 EVENT_ADMIN → 真实 bearer 登录 → 用该身份创建赛事。

本脚本只创建一场干净赛事并打印运行现场模拟需要的 id / 凭据：

```text
SINGLES / GROUP_KNOCKOUT / 16 席 / 4 组 / 每组 2 出线 / 6 张球台
```

**刻意不写 `registration_enabled`**：Day6D 要求「开启报名必须通过正式管理端 UI」，
因此报名开启由 `day6d_field_simulation.mjs` 在真实浏览器里点「保存报名设置」完成。
本脚本也不造选手 —— 16 名选手由 Public 报名 → 管理端确认产生（E5 链路本身）。

用法：

```powershell
cd backend
.\.venv\Scripts\python.exe .\day6d_field_fixture.py [base_url]
```

输出（供后续脚本消费）：

```text
TID=<赛事 id>
LOGIN_USERNAME=d6d-admin
LOGIN_PASSWORD=d6d-admin-pass1
TABLES=<逗号分隔的球台 id>
```
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

USERNAME = "d6d-admin"
PASSWORD = "d6d-admin-pass1"
DISPLAY_NAME = "D6D 现场模拟管理员"

TOURNAMENT_NAME = "D6D 现场模拟（16 人 4 组）"
TABLE_COUNT = 6
GROUP_COUNT = 4
QUALIFY_PER_GROUP = 2


def main() -> int:
    client: AuthClient = provision_event_admin(BASE, USERNAME, PASSWORD, DISPLAY_NAME)
    print(f"LOGIN_USERNAME={USERNAME}")
    print(f"LOGIN_PASSWORD={PASSWORD}")

    created = client.post(
        "/api/tournaments",
        {
            "name": TOURNAMENT_NAME,
            "date": "2026-10-01",
            "table_count": TABLE_COUNT,
            "group_count": GROUP_COUNT,
            "qualify_per_group": QUALIFY_PER_GROUP,
            "event_type": "SINGLES",
            "format_code": "GROUP_KNOCKOUT",
            "operation_mode": "LIVE",
            "games_to_win": 3,
            "points_to_win": 11,
        },
    )
    if created.status not in (200, 201):
        raise RuntimeError(f"创建赛事失败: HTTP {created.status} {created.body}")
    tid = created.body["id"]

    tournament = client.get(f"/api/tournaments/{tid}").body
    if tournament.get("registration_enabled") is not False:
        raise RuntimeError(f"新赛事报名开关必须默认 false，实际 {tournament.get('registration_enabled')}")
    if tournament.get("stage") != "REGISTRATION":
        raise RuntimeError(f"新赛事 stage 必须是 REGISTRATION，实际 {tournament.get('stage')}")
    if tournament.get("roster_confirmed"):
        raise RuntimeError("新赛事 roster_confirmed 必须是 false")

    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").body
    tables = [t["id"] for t in dashboard.get("tables", [])]
    if len(tables) != TABLE_COUNT:
        raise RuntimeError(f"球台数量应为 {TABLE_COUNT}，实际 {len(tables)}")

    print(f"TID={tid}")
    print(f"TABLES={','.join(str(t) for t in tables)}")
    print(f"NAME={tournament['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
