"""C 轨 Day5 Phase 4：管理端现场验收赛事 fixture。

## 与 D6D fixture 的关系

`day6d_field_fixture.py` 只创建**空赛事**（16 席 / 4 组 / 每組前 2 / 6 张球台，
报名开关留 false），因为 D6D 要求「16 名选手必须由 Public 报名 → 管理端确认产生」。
C 轨要验收的是**现场运行链**（Console 排台 / 录分 / Schedule / 打印），
因此本 fixture 在同一个赛事规模上把名单与小组赛推进到"可以开赛"的状态：

```text
16 人 / 4 组 / 每组 4 人 / 每组前 2 / 6 张球台 / GROUP_KNOCKOUT
```

## 边界

- 全程走**真实 HTTP 契约**（bootstrap → EVENT_ADMIN → bearer），没有任何直接写库；
- 选手用管理端 `POST /players` 手工录入（不是公开报名链路，也不是 demo 造数）；
- **不排台**：排台留给浏览器里的"自动安排下一批比赛"真实点击，这样现场验收才算数；
- 刻意不写 `registration_enabled`，避免与 D 轨报名开关语义混淆。

用法：

```powershell
cd backend
.\.venv\Scripts\python.exe .\c_day5_admin_fixture.py [base_url]
```

输出（供后续脚本消费）：

```text
TID=<赛事 id>
LOGIN_USERNAME=c5d-admin
LOGIN_PASSWORD=c5d-admin-pass1
TABLES=<逗号分隔的球台 id>
MATCHES=<生成的小组赛场数>
```
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

USERNAME = "c5d-admin"
PASSWORD = "c5d-admin-pass1"
DISPLAY_NAME = "C-D5 现场验收管理员"

TOURNAMENT_NAME = "C-D5 现场验收（16 人 / 4 组 / 6 台）"
PLAYER_COUNT = 16
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

    # 名单：管理端手工录入（真实写接口），并填写所属单位以贴近现场数据。
    for index in range(1, PLAYER_COUNT + 1):
        added = client.post(
            f"/api/tournaments/{tid}/players",
            {"name": f"选手{index:02d}", "affiliation": f"单位{index % 4 + 1}", "rating_points": 1000 + index},
        )
        if added.status not in (200, 201):
            raise RuntimeError(f"添加选手 {index} 失败: HTTP {added.status} {added.body}")

    confirmed = client.post(f"/api/tournaments/{tid}/confirm-roster")
    if confirmed.status != 200:
        raise RuntimeError(f"确认名单失败: HTTP {confirmed.status} {confirmed.body}")

    grouped = client.post(f"/api/tournaments/{tid}/auto-group")
    if grouped.status != 200:
        raise RuntimeError(f"生成分组失败: HTTP {grouped.status} {grouped.body}")

    generated = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    if generated.status != 200:
        raise RuntimeError(f"生成小组比赛失败: HTTP {generated.status} {generated.body}")

    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").body
    tables = [table["id"] for table in dashboard.get("tables", [])]
    completion = dashboard.get("completion", {})

    if len(tables) != TABLE_COUNT:
        raise RuntimeError(f"球台数量应为 {TABLE_COUNT}，实际 {len(tables)}")
    if completion.get("state") != "GROUP_STAGE_IN_PROGRESS":
        raise RuntimeError(f"生成小组赛后 completion 应为 GROUP_STAGE_IN_PROGRESS，实际 {completion}")
    if dashboard["stats"]["playing"] != 0:
        raise RuntimeError("fixture 不应预先排台：排台留给浏览器里的真实现场操作")

    print(f"TID={tid}")
    print(f"TABLES={','.join(str(t) for t in tables)}")
    print(f"MATCHES={generated.body.get('matches_generated')}")
    print(f"NAME={TOURNAMENT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
