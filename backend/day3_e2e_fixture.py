"""为 D 轨 Day3 手机端到端验收准备一场干净赛事，并打印 e2e 脚本需要的 id。

只调用现有 API，不改业务逻辑。配套脚本与运行前置见
`scripts_mobile_viewport_check.mjs` 文件头（Day 3 验收四件套）。

注意：`day3_mobile_e2e.mjs` 会把这些比赛**真的写成 FINISHED**，
因此每次重跑验收前都要重新执行本脚本，并使用新打印出来的 id。
"""

import json
import urllib.request

BASE = "http://127.0.0.1:8099"


def post(path: str, body: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


tournament = post(
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
tid = tournament["id"]

# 6 名选手 → 2 组 → 6 场小组赛，足够提供 A/C/D 三个互不干扰的场景
for name in ["张三", "李四", "王五", "赵六", "钱七", "孙八"]:
    post(f"/api/tournaments/{tid}/players", {"name": name})
post(f"/api/tournaments/{tid}/auto-group", {})
post(f"/api/tournaments/{tid}/generate-group-matches", {})

matches = get(f"/api/tournaments/{tid}/matches")
dashboard = get(f"/api/tournaments/{tid}/dashboard")
free_table = next(t for t in dashboard["tables"] if t["status"] == "FREE")
post(f"/api/matches/{matches[0]['id']}/assign-table", {"table_id": free_table["id"]})

print(f"TID={tid}")
print(f"MATCH_A={matches[0]['id']}")
print(f"MATCH_C={matches[1]['id']}")
print(f"MATCH_D={matches[2]['id']}")
