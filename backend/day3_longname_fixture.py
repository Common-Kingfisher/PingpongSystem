"""建一个"长名字 / 长赛事名"赛事，用于 D 轨 Day3 小屏适配的真实数据验收。

A 轨认证契约合入 master 后，创建赛事需要真实认证（`require_event_admin`），
且创建者自动成为赛事 OWNER；因此本脚本先真实登录 EVENT_ADMIN 再建数据。

建完后打印录分页路径（canonical 形式）供浏览器测量。
配套脚本与运行前置见 `scripts_mobile_viewport_check.mjs` 文件头（Day 3 验收四件套）。
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

USERNAME = "d3-longname-admin"
PASSWORD = "d3-longname-pass1"
DISPLAY_NAME = "D3 长名字验收管理员"


def main() -> int:
    client: AuthClient = provision_event_admin(BASE, USERNAME, PASSWORD, DISPLAY_NAME)
    print(f"LOGIN_USERNAME={USERNAME}")
    print(f"LOGIN_PASSWORD={PASSWORD}")

    created = client.post(
        "/api/tournaments",
        {
            "name": "2026 年秋季校级乒乓球联赛·男子单打·第一赛区（长名字测试）",
            "date": "2026-01-01",
            "table_count": 4,
            "group_count": 1,
            "qualify_per_group": 1,
            "event_type": "SINGLES",
            "operation_mode": "LIVE",
            "games_to_win": 2,
            "points_to_win": 11,
        },
    )
    if created.status not in (200, 201):
        raise RuntimeError(f"创建赛事失败: HTTP {created.status} {created.body}")
    tid = created.body["id"]

    # 故意使用超长名字：中文长名 + 长 ASCII 名（测试 overflow-wrap / line-clamp）
    for name in ["张三丰·欧阳锋·令狐冲·东方不败", "AlexandertheGreatWangXiaoming"]:
        added = client.post(f"/api/tournaments/{tid}/players", {"name": name})
        if added.status not in (200, 201):
            raise RuntimeError(f"添加选手失败: HTTP {added.status} {added.body}")

    client.post(f"/api/tournaments/{tid}/auto-group")
    generated = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    if generated.status not in (200, 201):
        raise RuntimeError(f"生成小组赛失败: HTTP {generated.status} {generated.body}")

    matches = client.get(f"/api/tournaments/{tid}/matches").body
    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").body
    free_table = next(t for t in dashboard["tables"] if t["status"] == "FREE")
    client.post(f"/api/matches/{matches[0]['id']}/assign-table", {"table_id": free_table["id"]})

    final = client.get(f"/api/tournaments/{tid}/matches").body[0]
    print(f"PATH=/admin/t/{tid}/matches/{final['id']}/score")
    print(f"A={final['entry_a_name']}")
    print(f"B={final['entry_b_name']}")
    print(f"tournament={created.body['name']}")
    print(f"TID={tid}")
    print(f"MATCH_ID={final['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
