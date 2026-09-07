"""冠军之路浏览器验收：真实依赖连线、冠军路径和窄屏可读性。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


TREE = {
    "tournament": {
        "id": 42,
        "name": "秋季乒乓球公开赛",
        "date": "2026-09-07",
        "table_count": 4,
        "group_count": 4,
        "qualify_per_group": 2,
        "stage": "FINISHED",
        "created_at": "2026-09-07 09:00:00",
        "event_type": "SINGLES",
        "bronze_mode": "BRONZE_MATCH",
        "placement_mode": "COMPLETE",
        "games_to_win": 2,
        "points_to_win": 11,
        "roster_confirmed": True,
        "confirmed_at": "2026-09-07 09:05:00",
    },
    "rounds": [
        {
            "round": 1,
            "label": "8强赛",
            "matches": [
                {"id": 101, "round": 1, "match_index": 0, "status": "FINISHED", "player_a": {"id": 1, "name": "张弛", "seed_no": 1, "member_names": ["张弛"]}, "player_b": {"id": 8, "name": "陈浩", "seed_no": 8, "member_names": ["陈浩"]}, "player_a_score": 2, "player_b_score": 0, "winner_id": 1, "table_id": 1, "prev_match_a_id": None, "prev_match_b_id": None, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
                {"id": 102, "round": 1, "match_index": 1, "status": "FINISHED", "player_a": {"id": 4, "name": "林峰", "seed_no": 4, "member_names": ["林峰"]}, "player_b": {"id": 5, "name": "韩飞", "seed_no": 5, "member_names": ["韩飞"]}, "player_a_score": 2, "player_b_score": 1, "winner_id": 4, "table_id": 2, "prev_match_a_id": None, "prev_match_b_id": None, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
                {"id": 103, "round": 1, "match_index": 2, "status": "FINISHED", "player_a": {"id": 2, "name": "李阳", "seed_no": 2, "member_names": ["李阳"]}, "player_b": {"id": 7, "name": "王晨", "seed_no": 7, "member_names": ["王晨"]}, "player_a_score": 2, "player_b_score": 1, "winner_id": 2, "table_id": 3, "prev_match_a_id": None, "prev_match_b_id": None, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
                {"id": 104, "round": 1, "match_index": 3, "status": "FINISHED", "player_a": {"id": 3, "name": "赵磊", "seed_no": 3, "member_names": ["赵磊"]}, "player_b": {"id": 6, "name": "周凯", "seed_no": 6, "member_names": ["周凯"]}, "player_a_score": 0, "player_b_score": 2, "winner_id": 6, "table_id": 4, "prev_match_a_id": None, "prev_match_b_id": None, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
            ],
        },
        {
            "round": 2,
            "label": "半决赛",
            "matches": [
                {"id": 105, "round": 2, "match_index": 0, "status": "FINISHED", "player_a": {"id": 1, "name": "张弛", "seed_no": 1, "member_names": ["张弛"]}, "player_b": {"id": 4, "name": "林峰", "seed_no": 4, "member_names": ["林峰"]}, "player_a_score": 2, "player_b_score": 1, "winner_id": 1, "table_id": 1, "prev_match_a_id": 101, "prev_match_b_id": 102, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
                {"id": 106, "round": 2, "match_index": 1, "status": "FINISHED", "player_a": {"id": 2, "name": "李阳", "seed_no": 2, "member_names": ["李阳"]}, "player_b": {"id": 6, "name": "周凯", "seed_no": 6, "member_names": ["周凯"]}, "player_a_score": 2, "player_b_score": 0, "winner_id": 2, "table_id": 2, "prev_match_a_id": 103, "prev_match_b_id": 104, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
            ],
        },
        {
            "round": 3,
            "label": "决赛",
            "matches": [
                {"id": 107, "round": 3, "match_index": 0, "status": "FINISHED", "player_a": {"id": 1, "name": "张弛", "seed_no": 1, "member_names": ["张弛"]}, "player_b": {"id": 2, "name": "李阳", "seed_no": 2, "member_names": ["李阳"]}, "player_a_score": 2, "player_b_score": 1, "winner_id": 1, "table_id": 1, "prev_match_a_id": 105, "prev_match_b_id": 106, "bracket": "MAIN", "placement_min": None, "placement_max": None, "result_type": "NORMAL"},
            ],
        },
    ],
    "champion": {"id": 1, "name": "张弛", "seed_no": 1, "member_names": ["张弛"]},
    "runner_up": {"id": 2, "name": "李阳", "seed_no": 2, "member_names": ["李阳"]},
    "placements": [],
    "placement_matches": [],
    "champion_path_match_ids": [101, 105, 107],
}


def test_champion_journey_connectors_and_responsive_layout():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.route("**/api/tournaments/42/knockout", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(TREE, ensure_ascii=False)))
        page.goto(f"{base_url}/journey?tid=42")

        expect(page.get_by_role("heading", name="秋季乒乓球公开赛")).to_be_visible()
        expect(page.locator(".journey-tree-match")).to_have_count(7)
        expect(page.locator(".journey-connectors path")).to_have_count(7)
        expect(page.locator(".journey-connectors path.is-champion-path")).to_have_count(3)
        expect(page.locator(".journey-summit h2")).to_have_text("张弛")
        expected_topology = [
            (101, 105), (102, 105), (103, 106), (104, 106),
            (105, 107), (106, 107), (107, "champion"),
        ]
        for source, target in expected_topology:
            expect(page.locator(
                f'.journey-connectors path[data-from-match="{source}"][data-to-match="{target}"]'
            )).to_have_count(1)
        screenshot_path = os.getenv("PINGPONG_E2E_SCREENSHOT")
        if screenshot_path:
            page.screenshot(path=screenshot_path, full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(".journey-tree")).to_be_visible()
        overflow = page.locator(".journey-page").evaluate(
            "element => ({ scrollWidth: element.scrollWidth, clientWidth: element.clientWidth })"
        )
        assert overflow["scrollWidth"] > overflow["clientWidth"]
        scroll_position = page.locator(".journey-page").evaluate(
            "element => { element.scrollLeft = 160; return element.scrollLeft }"
        )
        assert scroll_position > 0
        browser.close()


if __name__ == "__main__":
    test_champion_journey_connectors_and_responsive_layout()
