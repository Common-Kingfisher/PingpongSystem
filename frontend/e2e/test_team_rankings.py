"""团体排名浏览器验收：资格语义和并列名次。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


def tournament():
    return {
        "id": 42, "name": "秋季团体赛", "date": "2026-09-19", "table_count": 2,
        "group_count": 1, "qualify_per_group": 1, "stage": "REGISTRATION",
        "created_at": "2026-09-19 09:00:00", "event_type": "TEAM",
        "bronze_mode": "JOINT_BRONZE", "placement_mode": "OFF", "games_to_win": 2,
        "points_to_win": 11, "roster_confirmed": True, "confirmed_at": "2026-09-19 10:00:00",
        "operation_mode": "LIVE",
    }


def row(team_entry_id, name, rank, *, eligible=True, status="ACTIVE"):
    return {
        "team_entry_id": team_entry_id, "team_name": name, "status": status,
        "ties_played": 1, "ties_won": 1 if eligible else 0, "ties_lost": 0 if eligible else 1,
        "match_points": 2 if eligible else 1, "rubber_wins": 2, "rubber_losses": 1,
        "games_won": 4, "games_lost": 2, "rank_start": rank, "rank_end": rank,
        "ambiguous": False, "eligible_for_qualification": eligible,
        "qualification_position_state": "ELIGIBLE_ONLY" if rank > 1 else "RESOLVED",
    }


def test_team_rankings_distinguishes_outside_line_and_ineligible():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    standings = [{
        "group_id": 1, "group_name": "A组", "provisional": False, "ambiguous": False,
        "automatic_qualification_allowed": False, "qualify_count": 1,
        "standings": [
            row(1, "甲队", 1),
            row(2, "乙队", 2),
            row(3, "退赛队", 3, eligible=False, status="WITHDRAWN"),
        ],
    }]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        def route(request_route):
            url = request_route.request.url
            if url.endswith("/api/tournaments/42"):
                request_route.fulfill(status=200, content_type="application/json", body=json.dumps(tournament(), ensure_ascii=False))
            elif url.endswith("/api/tournaments/42/team-groups/standings"):
                request_route.fulfill(status=200, content_type="application/json", body=json.dumps(standings, ensure_ascii=False))
            else:
                request_route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-rankings?tid=42")

        expect(page.get_by_role("heading", name="秋季团体赛 · 团体排名")).to_be_visible()
        expect(page.get_by_text("退赛队")).to_be_visible()
        expect(page.locator(".team-standing-state").nth(1)).to_have_text("晋级线外")
        expect(page.locator(".team-standing-state").nth(2)).to_have_text("不可晋级")
        browser.close()
