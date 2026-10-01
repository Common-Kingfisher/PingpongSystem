"""D 轨 Day6D Phase 9：小屏 + 超长文本现场检查用的数据。

Day3 已有 `day3_longname_fixture.py`，但它造出的赛事**报名是关闭的**（新赛事默认），
因此无法用来测「Public 报名表单在 360/375/390/430 下的布局」。本脚本补上这一块：

```text
TID_OPEN  超长赛事名 + 报名已开启 + 2 条超长姓名 PENDING 报名
          → 用于测 /public/t/{tid}/register 的**表单态**（不是关闭态）

TID_PLAY  超长赛事名 + 超长选手名/单位名 + 名单已确认 + 已分组 + 已排台
          → 用于测 /public/t/{tid}/live|rankings|bracket 与 Mobile Score
```

两者都只用**正式 API**（真实 bootstrap → 真实 EVENT_ADMIN → 真实 bearer 调用），
不做任何绕过；本脚本产出的赛事与 Day6D 主模拟赛事（16 人 4 组）互不影响。

用法：

```powershell
cd backend
.\.venv\Scripts\python.exe .\day6d_longname_fixture.py [base_url]
```
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

USERNAME = "d6d-longname-admin"
PASSWORD = "d6d-longname-pass1"
DISPLAY_NAME = "D6D 小屏长文本验收管理员"

LONG_TOURNAMENT_NAME = (
    "2026 年秋季校级乒乓球联赛·男子单打·第一赛区"
    "（超长赛事名称用于现场小屏布局检查·含中英文混排 ABCDEFGHIJKLMNOPQRSTUVWXYZ）"
)
LONG_AFFILIATION = (
    "中华人民共和国某某省某某市某某区某某大学某某学院某某系某某专业某某年级超长所属单位名称"
)
LONG_NAMES = [
    "张三丰·欧阳锋·令狐冲·东方不败·独孤求败·风清扬",
    "AlexandertheGreatWangXiaomingZhangSanfeng",
    "李四光·钱学森·华罗庚·陈景润·苏步青·熊庆来",
    "BobTheBuilderSuperLongEnglishNameForOverflowTest",
]


def _create(client: AuthClient, name: str, *, tables: int, groups: int, registration: bool) -> int:
    created = client.post(
        "/api/tournaments",
        {
            "name": name,
            "date": "2026-10-01",
            "table_count": tables,
            "group_count": groups,
            "qualify_per_group": 1,
            "event_type": "SINGLES",
            "format_code": "GROUP_KNOCKOUT",
            "operation_mode": "LIVE",
            "games_to_win": 3,
            "points_to_win": 11,
            "registration_enabled": registration,
        },
    )
    if created.status not in (200, 201):
        raise RuntimeError(f"创建赛事失败: HTTP {created.status} {created.body}")
    return created.body["id"]


def main() -> int:
    client: AuthClient = provision_event_admin(BASE, USERNAME, PASSWORD, DISPLAY_NAME)
    print(f"LOGIN_USERNAME={USERNAME}")
    print(f"LOGIN_PASSWORD={PASSWORD}")

    # ---------------- TID_OPEN：报名开启 + 超长姓名 PENDING，用于测报名表单小屏 ----------------
    tid_open = _create(client, LONG_TOURNAMENT_NAME, tables=2, groups=1, registration=True)
    for index, name in enumerate(LONG_NAMES[:2], start=1):
        submitted = client.post(
            f"/api/tournaments/{tid_open}/registrations",
            {"name": name, "affiliation": LONG_AFFILIATION, "contact": None, "rating_points": 1200 + index},
        )
        if submitted.status != 201:
            raise RuntimeError(f"报名失败: HTTP {submitted.status} {submitted.body}")
    tournament_open = client.get(f"/api/tournaments/{tid_open}").body
    if tournament_open.get("registration_enabled") is not True:
        raise RuntimeError("TID_OPEN 的 registration_enabled 应为 true")
    print(f"TID_OPEN={tid_open}")

    # ---------------- TID_PLAY：名单已确认 + 已分组 + 已排台，用于长名字的实况/排名/录分 ----------------
    tid_play = _create(client, LONG_TOURNAMENT_NAME, tables=2, groups=1, registration=True)
    for name in LONG_NAMES:
        created = client.post(f"/api/tournaments/{tid_play}/registrations", {"name": name, "affiliation": LONG_AFFILIATION})
        if created.status != 201:
            raise RuntimeError(f"报名失败: HTTP {created.status} {created.body}")
    pending = client.get(f"/api/tournaments/{tid_play}/registrations?status=PENDING").body
    for item in pending:
        confirmed = client.post(f"/api/tournaments/{tid_play}/registrations/{item['id']}/confirm")
        if confirmed.status not in (200, 201):
            raise RuntimeError(f"确认报名失败: HTTP {confirmed.status} {confirmed.body}")

    roster = client.post(f"/api/tournaments/{tid_play}/confirm-roster")
    if roster.status not in (200, 201):
        raise RuntimeError(f"确认名单失败: HTTP {roster.status} {roster.body}")

    grouped = client.post(f"/api/tournaments/{tid_play}/auto-group")
    if grouped.status not in (200, 201):
        raise RuntimeError(f"生成分组失败: HTTP {grouped.status} {grouped.body}")

    generated = client.post(f"/api/tournaments/{tid_play}/generate-group-matches")
    if generated.status not in (200, 201):
        raise RuntimeError(f"生成小组赛失败: HTTP {generated.status} {generated.body}")

    dashboard = client.get(f"/api/tournaments/{tid_play}/dashboard").body
    matches = client.get(f"/api/tournaments/{tid_play}/matches").body
    free_table = next(t for t in dashboard["tables"] if t["status"] == "FREE")
    assigned = client.post(f"/api/matches/{matches[0]['id']}/assign-table", {"table_id": free_table["id"]})
    if assigned.status != 200:
        raise RuntimeError(f"排台失败: HTTP {assigned.status} {assigned.body}")

    final = client.get(f"/api/tournaments/{tid_play}/matches").body[0]
    print(f"TID_PLAY={tid_play}")
    print(f"MATCH_ID={final['id']}")
    print(f"A={final['entry_a_name']}")
    print(f"B={final['entry_b_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
