"""启动带团体名单测试数据的本地后端。

用法：
    python run_team_roster_demo.py --fresh

默认使用独立的 ``data/team_roster_demo.db``，不会碰日常 demo.db。启动后配合
``pnpm dev`` 打开输出的 /team-roster?tid= 地址，即可真实测试保存、确认与撤销冻结。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "team_roster_demo.db"
DEMO_NAME = "队伍名单工作表测试场"


def seed(fresh: bool) -> int:
    """创建三队名单，并保留两名未分队选手作为确认校验样本。"""
    sys.path.insert(0, str(ROOT))
    from app import db as db_module
    from app import repository as repo
    from app.models import EventType
    from app.services import teams
    from app.services import tournaments as tournament_service

    db_module.init_db()
    conn = db_module.connect()
    try:
        existing = [item for item in repo.list_tournaments(conn) if item["name"] == DEMO_NAME]
        if existing and not fresh:
            return existing[0]["id"]
        for item in existing:
            repo.delete_tournament(conn, item["id"])
        conn.commit()
        tournament = tournament_service.create_tournament_with_tables(
            conn, DEMO_NAME, date.today(), 3, 1, 1,
            event_type=EventType.TEAM.value, operation_mode="DEMO",
        )
        players = [
            repo.add_player(conn, tournament["id"], name, college, rating)
            for name, college, rating in [
                ("陈晨", "计算机学院", 1680), ("林航", "计算机学院", 1540), ("宋宁", "计算机学院", 1490),
                ("周敏", "自动化学院", 1660), ("吴越", "自动化学院", 1510), ("许诺", "自动化学院", 1460),
                ("高远", "电子信息学院", 1630), ("唐雨", "电子信息学院", 1530), ("方圆", "电子信息学院", 1450),
                ("待分队一", "机械学院", 1420), ("待分队二", "材料学院", 1380),
            ]
        ]
        teams.create_team_entry(conn, tournament["id"], "蓝海队", [player["id"] for player in players[0:3]])
        teams.create_team_entry(conn, tournament["id"], "晨星队", [player["id"] for player in players[3:6]])
        teams.create_team_entry(conn, tournament["id"], "远航队", [player["id"] for player in players[6:9]])
        return tournament["id"]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="启动团体名单工作表测试后端")
    parser.add_argument("--fresh", action="store_true", help="重置本测试数据库中的测试赛事")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    os.environ.setdefault("DEMO_DB_PATH", str(DEFAULT_DB))
    tournament_id = seed(args.fresh)
    print(f"[OK] 测试后端：http://127.0.0.1:{args.port}/api/health")
    print(f"[OK] 名单页面：http://127.0.0.1:5173/team-roster?tid={tournament_id}")
    print("[提示] 初始有 3 支队伍、9 名已分队队员和 2 名未分队队员；分配后可测试确认冻结。")
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
