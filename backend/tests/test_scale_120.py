"""120 人 / 15 台规模验收：导入、分组、循环赛、排名和 64 位淘汰签。"""

import csv
from pathlib import Path

import pytest
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "docs" / "demo-data" / "realistic_players_120.csv"
XLSX_PATH = ROOT / "docs" / "demo-data" / "realistic_players_120.xlsx"


def _play_all(client, tid: int, max_rounds: int = 100) -> None:
    """用真实排台接口批量推进，固定较小 ID 一方获胜，保证排名可复现。"""
    for _ in range(max_rounds):
        response = client.post(f"/api/tournaments/{tid}/schedule-next")
        assert response.status_code == 200, response.text
        dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
        playing = [table["match"] for table in dashboard["tables"] if table["match"]]
        if not playing:
            assert dashboard["stats"]["waiting"] == 0
            return
        for match in playing:
            if match["player_a_id"] < match["player_b_id"]:
                score = {"player_a_score": 2, "player_b_score": 0}
            else:
                score = {"player_a_score": 0, "player_b_score": 2}
            response = client.post(f"/api/matches/{match['id']}/score", json=score)
            assert response.status_code == 200, response.text
    raise AssertionError("超过 100 轮仍有待赛，可能存在排台死锁")


def test_realistic_roster_files_match_import_contract():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 120
    assert rows[0].keys() == {"姓名", "学院/单位", "运动员积分", "种子序号"}
    assert len({row["姓名"] for row in rows}) == 120
    assert all(760 <= int(row["运动员积分"]) <= 2200 for row in rows)
    assert [int(row["种子序号"]) for row in rows[:24]] == list(range(1, 25))
    assert all(row["种子序号"] == "" for row in rows[24:])

    workbook = load_workbook(XLSX_PATH, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    values = list(sheet.values)
    workbook.close()
    assert values[0] == ("姓名", "学院/单位", "运动员积分", "种子序号")
    assert len(values) == 121


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        (CSV_PATH, "text/csv"),
        (XLSX_PATH, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ],
)
def test_each_realistic_roster_file_imports_all_players(client, path, media_type):
    tournament_id = client.post(
        "/api/tournaments",
        json={
            "name": f"{path.suffix} 名单导入验收",
            "date": "2026-09-12",
            "table_count": 15,
            "group_count": 24,
            "qualify_per_group": 2,
        },
    ).json()["id"]

    response = client.post(
        f"/api/tournaments/{tournament_id}/players/import",
        files={"file": (path.name, path.read_bytes(), media_type)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 120
    assert response.json()["skipped"] == 0
    assert response.json()["errors"] == []
    players = client.get(f"/api/tournaments/{tournament_id}/players").json()
    assert len(players) == 120
    by_name = {player["name"]: player for player in players}
    assert by_name["陈子涵"]["rating_points"] == 1840
    assert by_name["陈子涵"]["seed_no"] == 1
    assert by_name["李梓辰"]["seed_no"] is None


def test_realistic_120_player_full_scale_flow(client):
    tournament = client.post(
        "/api/tournaments",
        json={
            "name": "2026 城市高校邀请赛规模验收",
            "date": "2026-09-12",
            "table_count": 15,
            "group_count": 24,
            "qualify_per_group": 2,
            "bronze_mode": "JOINT_BRONZE",
            "placement_mode": "OFF",
        },
    )
    assert tournament.status_code == 201, tournament.text
    tid = tournament.json()["id"]

    response = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": (CSV_PATH.name, CSV_PATH.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 120
    assert len(client.get(f"/api/tournaments/{tid}/players").json()) == 120

    response = client.post(f"/api/tournaments/{tid}/auto-group")
    assert response.status_code == 200, response.text
    groups = response.json()["groups"]
    assert len(groups) == 24
    assert sorted(len(group["players"]) for group in groups) == [5] * 24

    response = client.post(f"/api/tournaments/{tid}/generate-group-matches")
    assert response.status_code == 200, response.text
    assert response.json()["matches_generated"] == 240
    assert len(client.get(f"/api/tournaments/{tid}/matches?stage=GROUP").json()) == 240

    first_schedule = client.post(f"/api/tournaments/{tid}/schedule-next")
    assert first_schedule.status_code == 200, first_schedule.text
    first_dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert len(first_dashboard["tables"]) == 15
    assert first_dashboard["stats"]["playing"] == 15

    _play_all(client, tid)
    dashboard = client.get(f"/api/tournaments/{tid}/dashboard").json()
    assert dashboard["stats"] == {"total": 240, "finished": 240, "playing": 0, "waiting": 0}
    assert all(table["status"] == "FREE" for table in dashboard["tables"])

    rankings = client.get(f"/api/tournaments/{tid}/rankings").json()["rankings"]
    qualified = []
    for group in rankings:
        assert group["finished_matches"] == group["total_matches"] == 10
        assert group["ambiguous_qualification"] is False
        selected = [entry["player_id"] for entry in group["entries"] if entry["qualified"]]
        assert len(selected) == 2
        qualified.extend(selected)
    assert len(set(qualified)) == 48

    response = client.post(f"/api/tournaments/{tid}/generate-knockout")
    assert response.status_code == 200, response.text
    tree = response.json()
    assert [len(round_data["matches"]) for round_data in tree["rounds"]] == [32, 16, 8, 4, 2, 1]
    knockout_matches = client.get(f"/api/tournaments/{tid}/matches?stage=KNOCKOUT").json()
    assert len(knockout_matches) == 63
    assert sum(match["result_type"] == "WALKOVER" for match in knockout_matches) == 16

    _play_all(client, tid)
    final_tree = client.get(f"/api/tournaments/{tid}/knockout").json()
    assert final_tree["champion"] is not None
    assert final_tree["tournament"]["stage"] == "FINISHED"
