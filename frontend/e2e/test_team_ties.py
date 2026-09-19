"""团体对抗列表浏览器验收：名称映射、状态筛选和导航闭环。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


def tournament(event_type="TEAM"):
    return {
        "id": 42, "name": "秋季团体赛", "date": "2026-09-19", "table_count": 2,
        "group_count": 2, "qualify_per_group": 1, "stage": "REGISTRATION",
        "created_at": "2026-09-19 09:00:00", "event_type": event_type,
        "bronze_mode": "JOINT_BRONZE", "placement_mode": "OFF", "games_to_win": 2,
        "points_to_win": 11, "roster_confirmed": True, "confirmed_at": "2026-09-19 10:00:00",
        "operation_mode": "LIVE",
    }


def team(team_id, name, *, group_id=None):
    return {
        "id": team_id, "tournament_id": 42, "entry_type": "TEAM", "display_name": name,
        "rating_points": 0, "sort_order": team_id, "group_id": group_id, "seed_no": None,
        "status": "ACTIVE", "withdrawn_at": None, "withdrawn_by": None,
        "withdrawal_reason": None, "members": [],
    }


def tie(tie_id, home, away, *, group_id, stage="GROUP", round_no=1, match_index=1, status="WAITING", score=(0, 0)):
    return {
        "id": tie_id, "tournament_id": 42, "stage": stage, "group_id": group_id,
        "round": round_no, "match_index": match_index, "entry_a_id": home, "entry_b_id": away,
        "team_a_score": score[0], "team_b_score": score[1], "winner_entry_id": None,
        "status": status, "format_code": None, "format_version": None, "format_snapshot": None,
        "called_at": None, "started_at": None, "finished_at": None, "created_at": "2026-09-19 10:00:00",
    }


def install_routes(page, ties, *, list_failures=0, standings=None):
    failures = {"remaining": list_failures}
    groups = {
        "groups": [
            {"id": 2, "name": "B组", "sort_order": 2, "qualify_count": None, "players": [], "entries": []},
            {"id": 1, "name": "A组", "sort_order": 1, "qualify_count": None, "players": [], "entries": []},
        ]
    }

    def route(route):
        url = route.request.url
        if url.endswith("/api/tournaments/42"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(tournament(), ensure_ascii=False))
        elif url.endswith("/api/tournaments/42/teams"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps([team(1, "甲队", group_id=1), team(2, "乙队", group_id=1), team(3, "丙队", group_id=1)], ensure_ascii=False))
        elif url.endswith("/api/tournaments/42/groups"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(groups, ensure_ascii=False))
        elif url.endswith("/api/tournaments/42/team-ties"):
            if failures["remaining"]:
                failures["remaining"] -= 1
                route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "服务暂不可用"}, ensure_ascii=False))
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(ties, ensure_ascii=False))
        elif url.endswith("/api/tournaments/42/team-groups/standings"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(standings or [], ensure_ascii=False))
        else:
            route.continue_()

    page.route("**/api/**", route)


def test_team_ties_groups_filters_and_links():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    ties = [
        tie(13, 1, 2, group_id=1, round_no=2, match_index=1, status="FINISHED", score=(3, 1)),
        tie(11, 2, 3, group_id=1, round_no=1, match_index=2, status="WAITING"),
        tie(12, 1, 3, group_id=2, round_no=1, match_index=1, status="PLAYING", score=(1, 0)),
        tie(14, 1, 999, group_id=99, round_no=1, match_index=None, status="WAITING"),
        tie(15, 2, 3, group_id=None, round_no=1, status="WAITING"),
        tie(16, 1, 2, group_id=None, stage="KNOCKOUT", round_no=1, status="WAITING"),
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        install_routes(page, ties)
        page.goto(f"{base_url}/team-ties?tid=42")

        expect(page.get_by_role("heading", name="秋季团体赛 · 团体对抗")).to_be_visible()
        sections = page.locator(".team-ties-section")
        expect(sections).to_have_count(5)
        expect(sections.nth(0).get_by_role("heading")).to_have_text("A组 2 场")
        expect(sections.nth(1).get_by_role("heading")).to_have_text("B组 1 场")
        expect(sections.nth(2).get_by_role("heading")).to_have_text("小组 #99 1 场")
        expect(sections.nth(3).get_by_role("heading")).to_have_text("未分组对抗 1 场")
        expect(sections.nth(4).get_by_role("heading")).to_have_text("淘汰赛 1 场")
        expect(page.get_by_text("队伍 #999")).to_be_visible()
        expect(sections.nth(0).locator("tbody tr").nth(0)).to_contain_text("第 1 轮")
        expect(page.get_by_role("link", name="进入对抗").nth(0)).to_have_attribute("href", "/team-tie?tid=42&tie=11")
        expect(page.get_by_role("link", name="团体对抗")).to_be_visible()
        expect(page.get_by_role("link", name="比赛控制台")).to_have_count(0)

        page.set_viewport_size({"width": 375, "height": 720})
        expect(page.locator(".team-ties-table thead").first).to_be_hidden()
        expect(page.locator(".team-ties-table td[data-label]")).to_have_count(30)
        expect(page.locator(".team-ties-table td[data-label='操作']").first).to_contain_text("进入对抗")

        page.get_by_role("button", name="进行中 1").click()
        expect(sections).to_have_count(1)
        expect(page.get_by_text("丙队", exact=True)).to_be_visible()
        page.get_by_role("button", name="已结束 1").click()
        expect(page.get_by_text("3 : 1")).to_be_visible()
        page.get_by_role("button", name="待开始 4").click()
        expect(sections).to_have_count(4)
        browser.close()


def test_team_ties_empty_retry_and_invalid_id():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()
        install_routes(page, [], list_failures=1)
        page.goto(f"{base_url}/team-ties?tid=42")
        expect(page.get_by_role("alert")).to_contain_text("服务暂不可用")
        page.get_by_role("button", name="重试").click()
        expect(page.get_by_role("heading", name="尚无团体对抗")).to_be_visible()

        page.goto(f"{base_url}/team-ties?tid=bad")
        expect(page.get_by_text("请提供有效的")).to_be_visible()
        browser.close()


def test_team_ties_matrix_scores_and_standings():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    ties = [
        tie(21, 1, 2, group_id=1, round_no=1, status="FINISHED", score=(3, 1)),
        tie(22, 2, 3, group_id=1, round_no=2, status="PLAYING", score=(1, 0)),
        tie(23, 1, 3, group_id=1, round_no=3, status="WAITING"),
    ]
    standings = [{
        "group_id": 1, "group_name": "A组", "provisional": True, "ambiguous": True,
        "automatic_qualification_allowed": False, "qualify_count": 1,
        "standings": [
            {"team_entry_id": 1, "team_name": "甲队", "match_points": 3, "rank_start": 1, "rank_end": 2, "ambiguous": True},
            {"team_entry_id": 2, "team_name": "乙队", "match_points": 3, "rank_start": 1, "rank_end": 2, "ambiguous": True},
            {"team_entry_id": 3, "team_name": "丙队", "match_points": 0, "rank_start": 3, "rank_end": 3, "ambiguous": False},
        ],
    }]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        install_routes(page, ties, standings=standings)
        page.goto(f"{base_url}/team-ties?tid=42&view=matrix")

        expect(page.locator(".team-matrix-table")).to_have_count(1)
        expect(page.locator(".team-matrix-row-head").nth(0)).to_contain_text("甲队")
        expect(page.locator(".team-matrix-cell.finished").nth(0)).to_contain_text("3:1")
        expect(page.locator(".team-matrix-cell.playing").nth(0)).to_contain_text("1:0")
        expect(page.locator(".team-matrix-cell.waiting").nth(0)).to_contain_text("—")
        expect(page.locator(".team-matrix-total.rank").nth(0)).to_contain_text("1-2")
        expect(page.locator(".team-matrix-cell.finished a").nth(0)).to_have_attribute("href", "/team-tie?tid=42&tie=21")
        browser.close()
