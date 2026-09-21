"""启动团体晋级与淘汰签真实浏览器验收所需的独立后端。

创建四个两队小组并完成每场小组对抗。前端测试通过真实 API 确认八支
自动晋级队伍，再生成首轮四场淘汰对抗；不会触碰默认 ``demo.db``。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "team_qualification_knockout_demo.db"
DEMO_NAME = "团体晋级淘汰签真实联调场"
FORMAT_CODE = "LOCAL_CLASSIC_5_V1"


def _finish_tie(conn, tournament_id: int, tie_id: int) -> None:
    """按既有运行态服务真实完成一场 3:0 对抗。"""
    from app import repository as repo
    from app.services import team_runtime, team_ties

    team_ties.build_rubber_skeleton(conn, tournament_id, tie_id, FORMAT_CODE)
    tie = repo.get_team_tie(conn, tie_id)
    for sequence in range(1, 4):
        view = team_runtime.runtime_view(conn, tournament_id, tie_id)
        rubber = next(item for item in view["rubbers"] if item["sequence"] == sequence)
        slots = 2 if rubber["rubber_type"] == "DOUBLES" else 1
        home_ids = [item["player_id"] for item in view["home_team"]["members"]][:slots]
        away_ids = [item["player_id"] for item in view["away_team"]["members"]][:slots]
        team_runtime.set_lineup(conn, tournament_id, tie_id, rubber["id"], home_ids, away_ids)
        team_runtime.start_rubber(conn, tournament_id, tie_id, rubber["id"])
        team_runtime.record_rubber_score(conn, tournament_id, tie_id, rubber["id"], 2, 0)
        if repo.get_team_tie(conn, tie_id)["status"] == "FINISHED":
            break


def seed(fresh: bool) -> int:
    sys.path.insert(0, str(ROOT))
    from app import db as db_module
    from app import repository as repo
    from app.models import EventType
    from app.services import team_ties, teams
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
            conn, DEMO_NAME, date.today(), 4, 4, 2,
            event_type=EventType.TEAM.value, operation_mode="DEMO",
        )
        players = [
            repo.add_player(conn, tournament["id"], f"晋级联调选手{index:02d}", "联调组", 1200 + index)
            for index in range(1, 33)
        ]
        conn.commit()
        for index in range(8):
            teams.create_team_entry(
                conn,
                tournament["id"],
                f"联调队{index + 1}",
                [player["id"] for player in players[index * 4 : (index + 1) * 4]],
            )
        groups = [
            repo.create_group(conn, tournament["id"], f"{name}组", sort_order)
            for sort_order, name in enumerate(("A", "B", "C", "D"), start=1)
        ]
        entries = repo.list_entries_by_type(conn, tournament["id"], EventType.TEAM.value)
        for index, entry in enumerate(entries):
            repo.set_entry_group(conn, entry["id"], groups[index // 2]["id"])
        conn.commit()

        team_ties.generate_group_ties(conn, tournament["id"])
        for tie in repo.list_team_ties(conn, tournament["id"]):
            _finish_tie(conn, tournament["id"], tie["id"])
        return tournament["id"]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="启动团体晋级与淘汰签真实联调后端")
    parser.add_argument("--fresh", action="store_true", help="重建独立联调数据库")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    database = Path(os.environ.get("TEAM_QUALIFICATION_KNOCKOUT_DEMO_DB_PATH", str(DEFAULT_DB))).resolve()
    if database == (ROOT / "data" / "demo.db").resolve():
        raise SystemExit("TEAM_QUALIFICATION_KNOCKOUT_DEMO_DB_PATH 不能指向默认 demo.db")
    os.environ["DEMO_DB_PATH"] = str(database)
    tournament_id = seed(args.fresh)
    print(f"[OK] 后端：http://127.0.0.1:{args.port}/api/health")
    print(f"[OK] 晋级确认：http://127.0.0.1:5173/team-qualification?tid={tournament_id}")
    print(f"[OK] 淘汰签：http://127.0.0.1:5173/team-knockout?tid={tournament_id}")
    print(f"[OK] E2E：$env:TEAM_QUALIFICATION_KNOCKOUT_E2E_TID = \"{tournament_id}\"")
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
