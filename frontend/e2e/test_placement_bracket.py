"""完整排位赛浏览器验收：按名次区间分组且主签/排位语义清楚。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


TOURNAMENT = {
    "id": 42,
    "name": "十六强排位验收赛",
    "date": "2026-09-08",
    "table_count": 4,
    "group_count": 8,
    "qualify_per_group": 2,
    "stage": "KNOCKOUT",
    "created_at": "2026-09-08 09:00:00",
    "event_type": "SINGLES",
    "bronze_mode": "BRONZE_MATCH",
    "placement_mode": "COMPLETE",
    "games_to_win": 2,
    "points_to_win": 11,
    "roster_confirmed": True,
    "confirmed_at": "2026-09-08 09:05:00",
}


def participant(entry_id, name):
    return {"id": entry_id, "name": name, "seed_no": None, "member_names": [name]}


def placement(match_id, low, high, round_no, a, b):
    return {
        "range": [low, high],
        "match": {
            "id": match_id,
            "round": round_no,
            "match_index": 0,
            "status": "WAITING",
            "player_a": participant(a, f"选手{a:02d}"),
            "player_b": participant(b, f"选手{b:02d}"),
            "player_a_score": None,
            "player_b_score": None,
            "winner_id": None,
            "table_id": None,
            "prev_match_a_id": match_id - 10,
            "prev_match_b_id": match_id - 9,
            "bracket": "PLACEMENT",
            "placement_min": low,
            "placement_max": high,
            "result_type": None,
        },
    }


TREE = {
    "tournament": TOURNAMENT,
    "rounds": [{
        "round": 1,
        "label": "决赛",
        "matches": [{
            "id": 1, "round": 1, "match_index": 0, "status": "WAITING",
            "player_a": participant(1, "选手01"), "player_b": participant(2, "选手02"),
            "player_a_score": None, "player_b_score": None, "winner_id": None,
            "table_id": None, "prev_match_a_id": None, "prev_match_b_id": None,
            "bracket": "MAIN", "placement_min": None, "placement_max": None,
            "result_type": None,
        }],
    }],
    "champion": None,
    "runner_up": None,
    "placements": [],
    "placement_matches": [
        placement(101, 3, 4, 1, 3, 4),
        placement(102, 9, 16, 1, 9, 10),
        placement(103, 9, 16, 2, 11, 12),
        placement(104, 9, 16, 3, 13, 14),
        placement(105, 13, 16, 1, 15, 16),
        placement(106, 15, 16, 1, 17, 18),
    ],
    "champion_path_match_ids": [],
}


def test_placement_matches_are_grouped_by_rank_band():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1100})

        def api_route(route):
            url = route.request.url
            if url.endswith("/api/tournaments/42/knockout"):
                body = TREE
            elif url.endswith("/api/tournaments/42/rankings"):
                body = {"tournament": TOURNAMENT, "rankings": []}
            elif url.endswith("/api/tournaments/42"):
                body = TOURNAMENT
            else:
                route.fallback()
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

        page.route("**/api/**", api_route)
        page.goto(f"{base_url}/knockout?tid=42")

        expect(page.get_by_role("heading", name="季军与完整名次排位")).to_be_visible()
        expect(page.locator(".placement-band")).to_have_count(4)
        expect(page.get_by_role("heading", name="9–16 名排位")).to_be_visible()
        expect(page.get_by_text("9/10 名决胜")).to_be_visible()
        expect(page.get_by_text("每个名次区间独立比赛，负者不会返回冠军主签")).to_be_visible()
        screenshot_path = os.getenv("PINGPONG_E2E_PLACEMENT_SCREENSHOT")
        if screenshot_path:
            page.screenshot(path=screenshot_path, full_page=True)
        browser.close()


if __name__ == "__main__":
    test_placement_matches_are_grouped_by_rank_band()
