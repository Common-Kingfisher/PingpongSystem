"""删除并重新添加选手后，分组卡片仍按 Entry 显示正确的种子标识。"""

import os

from playwright.sync_api import expect, sync_playwright


def test_seed_badge_after_player_readded() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:5174")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        tournament_response = page.request.post(
            f"{base_url}/api/tournaments",
            data={
                "name": "种子图标回归测试",
                "date": "2026-09-08",
                "table_count": 4,
                "group_count": 4,
                "qualify_per_group": 1,
                "operation_mode": "DEMO",
                "event_type": "SINGLES",
                "bronze_mode": "JOINT_BRONZE",
                "placement_mode": "OFF",
            },
        )
        assert tournament_response.status == 201
        tournament_id = tournament_response.json()["id"]

        generated_response = page.request.post(
            f"{base_url}/api/tournaments/{tournament_id}/demo/generate-players",
            data={"count": 4, "with_seeds": True},
        )
        assert generated_response.status == 200
        original_players = generated_response.json()

        deleted_id = original_players[-1]["id"]
        assert page.request.delete(
            f"{base_url}/api/tournaments/{tournament_id}/players/{deleted_id}"
        ).status == 204
        replacement_response = page.request.post(
            f"{base_url}/api/tournaments/{tournament_id}/players",
            data={"name": "重建四号种子", "college": "测试队", "rating_points": 2000},
        )
        assert replacement_response.status == 201
        replacement_id = replacement_response.json()["id"]
        assert replacement_id != deleted_id

        seed_ids = [player["id"] for player in original_players[:3]] + [replacement_id]
        assert page.request.put(
            f"{base_url}/api/tournaments/{tournament_id}/seeds",
            data={"player_ids": seed_ids},
        ).status == 200
        assert page.request.post(
            f"{base_url}/api/tournaments/{tournament_id}/confirm-roster"
        ).status == 200
        assert page.request.post(
            f"{base_url}/api/tournaments/{tournament_id}/auto-group"
        ).status == 200

        page.goto(f"{base_url}/players?tid={tournament_id}")
        page.wait_for_load_state("networkidle")
        replacement_row = page.locator(".group-card li").filter(has_text="重建四号种子")
        expect(replacement_row).to_contain_text("⭐4")
        assert page.request.delete(
            f"{base_url}/api/tournaments/{tournament_id}"
        ).status == 204
        browser.close()


if __name__ == "__main__":
    test_seed_badge_after_player_readded()
