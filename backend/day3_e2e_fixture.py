"""为 D 轨 Day3 手机端到端验收准备一场干净赛事，并打印 e2e 脚本需要的 id 与登录凭据。

A 轨认证契约合入 master 后，创建赛事本身也需要真实认证（`require_event_admin`
+ 创建后自动成为赛事 OWNER），因此本脚本：

1. 真实 Bootstrap（若尚未初始化）→ 真实建 EVENT_ADMIN → 真实 `/api/v1/auth/login` 拿 Bearer；
2. 用该身份创建赛事 / 选手 / 分组 / 小组赛，并把第一场排上台；
3. 打印 tid、四个互不干扰的 matchId，以及浏览器 E2E 登录用的账号密码。

**没有**任何绕过：不关鉴权、不 override dependency、不因为本机来源就放行。

注意：`day3_mobile_e2e.mjs` 会把这些比赛**真的写成 FINISHED**，
因此每次重跑验收前都要重新执行本脚本，并使用新打印出来的 id。
"""

from __future__ import annotations

import sys

from day3_auth_client import AuthClient, provision_event_admin

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"

USERNAME = "d3-e2e-admin"
PASSWORD = "d3-e2e-admin-pass1"
DISPLAY_NAME = "D3 端到端验收管理员"


def main() -> int:
    client: AuthClient = provision_event_admin(BASE, USERNAME, PASSWORD, DISPLAY_NAME)
    print(f"LOGIN_USERNAME={USERNAME}")
    print(f"LOGIN_PASSWORD={PASSWORD}")

    created = client.post(
        "/api/tournaments",
        {
            "name": "D3 手机端到端验收（可删）",
            "date": "2026-01-01",
            "table_count": 4,
            "group_count": 2,
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

    for name in ["张三", "李四", "王五", "赵六", "钱七", "孙八"]:
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

    print(f"TID={tid}")
    print(f"MATCH_A={matches[0]['id']}")
    print(f"MATCH_C={matches[1]['id']}")
    print(f"MATCH_D={matches[2]['id']}")
    print(f"MATCH_B={matches[3]['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
