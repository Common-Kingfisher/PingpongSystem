"""启动可供前端真实团体对抗验收使用的独立后端。

创建两支四人队、一个小组、一场已建盘的五盘三胜对抗；不触碰默认 demo.db。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "team_tie_demo.db"
DEMO_NAME = "团体对抗真实联调场"


def seed(fresh: bool) -> tuple[int, int]:
    sys.path.insert(0, str(ROOT))
    from app import db as db_module
    from app import repository as repo
    from app.models import EventType
    from app.services import entries, team_ties, teams, tournaments

    db_module.init_db()
    conn = db_module.connect()
    try:
        existing = [item for item in repo.list_tournaments(conn) if item["name"] == DEMO_NAME]
        if existing and not fresh:
            tie = repo.list_team_ties(conn, existing[0]["id"])[0]
            return existing[0]["id"], tie["id"]
        for item in existing:
            repo.delete_tournament(conn, item["id"])
        conn.commit()
        tournament = tournaments.create_tournament_with_tables(
            conn, DEMO_NAME, date.today(), 2, 1, 1,
            event_type=EventType.TEAM.value, operation_mode="DEMO",
        )
        player_ids = [
            repo.add_player(conn, tournament["id"], f"联调选手{index}", "联调组", 1000 + index)["id"]
            for index in range(1, 9)
        ]
        conn.commit()
        home = teams.create_team_entry(conn, tournament["id"], "蓝海队", player_ids[:4])
        away = teams.create_team_entry(conn, tournament["id"], "晨星队", player_ids[4:])
        entries.confirm_roster(conn, tournament["id"])
        group = repo.create_group(conn, tournament["id"], "A组", 1)
        repo.set_entry_group(conn, home["id"], group["id"])
        repo.set_entry_group(conn, away["id"], group["id"])
        conn.commit()
        team_ties.generate_group_ties(conn, tournament["id"])
        tie = repo.list_team_ties(conn, tournament["id"])[0]
        team_ties.build_rubber_skeleton(conn, tournament["id"], tie["id"], "LOCAL_CLASSIC_5_V1")
        return tournament["id"], tie["id"]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="启动团体对抗真实联调后端")
    parser.add_argument("--fresh", action="store_true", help="重建独立联调数据库")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    database = Path(os.environ.get("TEAM_TIE_DEMO_DB_PATH", str(DEFAULT_DB))).resolve()
    if database == (ROOT / "data" / "demo.db").resolve():
        raise SystemExit("TEAM_TIE_DEMO_DB_PATH 不能指向默认 demo.db")
    os.environ["DEMO_DB_PATH"] = str(database)
    tid, tie_id = seed(args.fresh)
    print(f"[OK] 后端：http://127.0.0.1:{args.port}/api/health")
    print(f"[OK] 对抗：http://127.0.0.1:5173/team-tie?tid={tid}&tie={tie_id}")
    print(f"[OK] 排名：http://127.0.0.1:5173/team-rankings?tid={tid}")
    print(f"[OK] E2E：$env:TEAM_TIE_E2E_TID = \"{tid}\"; $env:TEAM_TIE_E2E_TIE_ID = \"{tie_id}\"")
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
