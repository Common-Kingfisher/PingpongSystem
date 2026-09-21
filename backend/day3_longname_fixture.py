"""建一个"长名字 / 长赛事名"赛事，用于 D 轨 Day3 小屏适配的真实数据验收。

本脚本只调用现有 API，不改业务逻辑；建完后打印录分页路径供浏览器测量。
配套脚本与运行前置见 `scripts_mobile_viewport_check.mjs` 文件头（Day 3 验收四件套）。
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
tid = tournament["id"]

# 故意使用超长名字：中文长名 + 长 ASCII 名（测试 overflow-wrap / line-clamp）
long_name_a = "张三丰·欧阳锋·令狐冲·东方不败"
long_name_b = "AlexandertheGreatWangXiaoming"
post(f"/api/tournaments/{tid}/players", {"name": long_name_a})
post(f"/api/tournaments/{tid}/players", {"name": long_name_b})
post(f"/api/tournaments/{tid}/auto-group", {})
post(f"/api/tournaments/{tid}/generate-group-matches", {})

matches = get(f"/api/tournaments/{tid}/matches")
dashboard = get(f"/api/tournaments/{tid}/dashboard")
free_table = next(t for t in dashboard["tables"] if t["status"] == "FREE")
post(f"/api/matches/{matches[0]['id']}/assign-table", {"table_id": free_table["id"]})

final = get(f"/api/tournaments/{tid}/matches")[0]
print(f"PATH=/admin/t/{tid}/score/{final['id']}")
print(f"A={final['entry_a_name']}")
print(f"B={final['entry_b_name']}")
print(f"tournament={tournament['name']}")
