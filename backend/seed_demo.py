"""Demo 种子脚本：一键创建 24 名选手 / 6 张球台 / 4 组×6 人的演示赛事。

用法：
    python seed_demo.py            # 已存在同名演示赛事则直接复用
    python seed_demo.py --fresh    # 删除旧的演示赛事后重建

生成的赛事已完成自动分组与小组赛生成（60 场待赛），
打开前端后进入「比赛控制台」即可开始调度与录分。
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db as db_module
from app import repository as repo
from app.services import groups as groups_service
from app.services import matches as matches_service
from app.services import tournaments as tournament_service

DEMO_NAME = "演示赛事（24人/6台）"


def main() -> int:
    fresh = "--fresh" in sys.argv
    db_module.init_db()
    conn = db_module.connect()
    try:
        existing = [t for t in repo.list_tournaments(conn) if t["name"] == DEMO_NAME]
        if existing and not fresh:
            _print_ready(existing[0])
            return 0
        if existing and fresh:
            repo.delete_tournament(conn, existing[0]["id"])
            conn.commit()
            print("已删除旧演示赛事")

        tournament = tournament_service.create_tournament_with_tables(
            conn, DEMO_NAME, date(2025, 6, 1), 6, 4, 2,
            operation_mode="DEMO",
        )
        for i in range(1, 25):
            repo.add_player(conn, tournament["id"], f"选手{i:02d}", "示例学院")
        conn.commit()

        groups_service.auto_group_tournament(conn, tournament["id"])
        total, per_group = matches_service.generate_group_matches(conn, tournament["id"])

        print(f"[OK] 演示赛事已创建：id={tournament['id']}（{DEMO_NAME}）")
        print(f"   24 名选手（选手01~选手24）已自动分为 4 组 × 6 人")
        print(f"   已生成小组赛 {total} 场：{'，'.join(f'{g} {n} 场' for g, n in per_group.items())}")
        print(f"   赛事阶段：{repo.get_tournament(conn, tournament['id'])['stage']}")
        _print_ready(repo.get_tournament(conn, tournament["id"]))
        return 0
    finally:
        conn.close()


def _print_ready(tournament: dict) -> None:
    print(f"\n演示赛事已就绪：id={tournament['id']}")
    print("打开 http://localhost:5173/?tid=" + str(tournament["id"]) + " 开始操作。")
    print("推荐流程：比赛控制台（一键调度 -> 录入比分）-> 小组排名 -> 淘汰赛 -> 冠军。")


if __name__ == "__main__":
    raise SystemExit(main())
