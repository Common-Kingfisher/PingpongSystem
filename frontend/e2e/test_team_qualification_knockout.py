"""团体晋级与淘汰签页面：只消费 A6.3/A6.4 服务端事实，不推导种子或后续胜者。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


TOURNAMENT = {"id": 42, "name": "团体晋级验收场", "event_type": "TEAM"}


def qualification(confirmed=None, blocked_reasons=None):
    confirmed = confirmed or []
    ids = [item["team_entry_id"] for item in confirmed]
    return {
        "tournament_id": 42, "provisional": False, "requires_manual_resolution": True,
        "can_confirm": False, "blocked_reasons": blocked_reasons or [], "confirmed": confirmed,
        "groups": [{
            "group_id": 1, "group_name": "A组", "qualify_count": 2, "provisional": False,
            "requires_manual_resolution": True, "can_confirm": False,
            "auto_qualified_team_ids": [11], "boundary_tied_team_ids": [12, 13],
            "boundary_slots_remaining": 1, "blocked_reasons": [], "confirmed_team_ids": ids,
            "candidates": [
                {"team_entry_id": 11, "team_name": "A1队", "auto_qualified": True, "on_boundary_tie": False},
                {"team_entry_id": 12, "team_name": "A2队", "auto_qualified": False, "on_boundary_tie": True},
                {"team_entry_id": 13, "team_name": "A3队", "auto_qualified": False, "on_boundary_tie": True},
            ],
        }],
    }


def knockout(generated=False):
    if not generated:
        return {"tournament_id": 42, "generated": False, "rounds": [], "ties": []}
    first = {
        "tie_id": 71, "round": 1, "round_name": "四分之一决赛", "match_index": 1,
        "teams_decided": True, "team_a": {"team_entry_id": 11, "team_name": "A1队"},
        "team_b": {"team_entry_id": 22, "team_name": "B2队"}, "status": "WAITING",
        "team_a_score": 0, "team_b_score": 0, "winner_entry_id": None,
    }
    return {"tournament_id": 42, "generated": True, "ties": [first], "rounds": [
        {"round": 1, "round_name": "四分之一决赛", "match_count": 1, "matches": [first]},
        {"round": 2, "round_name": "半决赛", "match_count": 1, "matches": []},
    ]}


CONFIRMED_TEAMS = [
    {"team_entry_id": 11, "team_name": "A1队", "group_id": 1, "group_name": "A组", "status": "ACTIVE", "confirmed_at": "2026-09-20 12:00:00"},
    {"team_entry_id": 12, "team_name": "A2队", "group_id": 1, "group_name": "A组", "status": "ACTIVE", "confirmed_at": "2026-09-20 12:00:00"},
]


def test_team_qualification_submits_full_manual_selection():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    submitted = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()

        def route(route):
            if route.request.url.endswith("/api/tournaments/42"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(TOURNAMENT))
            elif route.request.url.endswith("/api/tournaments/42/qualification/confirm"):
                submitted.append(route.request.post_data_json)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification([
                    {"team_entry_id": 11, "team_name": "A1队", "group_id": 1, "group_name": "A组", "status": "ACTIVE", "confirmed_at": "2026-09-20 12:00:00"},
                    {"team_entry_id": 12, "team_name": "A2队", "group_id": 1, "group_name": "A组", "status": "ACTIVE", "confirmed_at": "2026-09-20 12:00:00"},
                ]), ensure_ascii=False))
            elif route.request.url.endswith("/api/tournaments/42/qualification"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification(), ensure_ascii=False))
            else:
                route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-qualification?tid=42")
        expect(page.get_by_role("heading", name="团体晋级验收场 · 晋级确认")).to_be_visible()
        expect(page.get_by_text("系统不会按队伍编号或展示顺序自动决定")).to_be_visible()
        candidates = page.get_by_label("A组 晋级队伍").locator('input[type="checkbox"]')
        expect(candidates.nth(0)).to_be_checked()
        candidates.nth(1).check()
        page.get_by_role("button", name="确认晋级名单").click()
        assert submitted == [{"qualified_team_ids": [11, 12]}]
        expect(page.get_by_role("heading", name="已确认队伍")).to_be_visible()
        expect(page.get_by_role("link", name="前往团体淘汰签")).to_be_visible()
        browser.close()


def test_team_qualification_recovers_after_candidate_change():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    stale_confirmed = [
        *CONFIRMED_TEAMS[:1],
        {"team_entry_id": 99, "team_name": "已退赛队", "group_id": 1, "group_name": "A组", "status": "WITHDRAWN", "confirmed_at": "2026-09-20 12:00:00"},
    ]
    submitted = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()

        def route(route):
            if route.request.url.endswith("/api/tournaments/42"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(TOURNAMENT))
            elif route.request.url.endswith("/api/tournaments/42/qualification/confirm"):
                payload = route.request.post_data_json
                submitted.append(payload)
                if 99 in payload["qualified_team_ids"]:
                    route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "队伍不属于当前晋级候选"}, ensure_ascii=False))
                    return
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification(CONFIRMED_TEAMS), ensure_ascii=False))
            elif route.request.url.endswith("/api/tournaments/42/qualification"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification(stale_confirmed), ensure_ascii=False))
            else:
                route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-qualification?tid=42")
        expect(page.get_by_role("heading", name="团体晋级验收场 · 晋级确认")).to_be_visible()
        candidates = page.get_by_label("A组 晋级队伍").locator('input[type="checkbox"]')
        expect(candidates.nth(0)).to_be_checked()
        expect(candidates.nth(1)).not_to_be_checked()
        update = page.get_by_role("button", name="更新晋级名单")
        expect(update).to_be_disabled()
        candidates.nth(1).check()
        expect(update).to_be_enabled()
        update.click()
        assert submitted == [{"qualified_team_ids": [11, 12]}]
        expect(page.get_by_role("heading", name="已确认队伍")).to_be_visible()
        browser.close()


def test_team_qualification_respects_server_blocked_reasons():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()

        def route(route):
            if route.request.url.endswith("/api/tournaments/42"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(TOURNAMENT))
            elif route.request.url.endswith("/api/tournaments/42/qualification"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification(blocked_reasons=["A组候选队伍数量不足"]), ensure_ascii=False))
            else:
                route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-qualification?tid=42")
        expect(page.get_by_text("当前不能确认")).to_be_visible()
        expect(page.get_by_role("button", name="确认晋级名单")).to_be_disabled()
        browser.close()


def test_team_knockout_keeps_future_rounds_pending():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()

        def route(route):
            if route.request.url.endswith("/api/tournaments/42"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(TOURNAMENT))
            elif route.request.url.endswith("/api/tournaments/42/team-knockout/generate"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(knockout(True), ensure_ascii=False))
            elif route.request.url.endswith("/api/tournaments/42/team-knockout"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(knockout(), ensure_ascii=False))
            elif route.request.url.endswith("/api/tournaments/42/qualification"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification(CONFIRMED_TEAMS), ensure_ascii=False))
            else:
                route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-knockout?tid=42")
        page.get_by_role("button", name="生成首轮淘汰签").click()
        expect(page.get_by_role("heading", name="四分之一决赛")).to_be_visible()
        expect(page.get_by_role("link", name="进入对抗")).to_have_attribute("href", "/team-tie?tid=42&tie=71")
        semifinal = page.locator(".team-knockout-round").filter(has_text="半决赛")
        expect(semifinal.get_by_text("待上游胜者")).to_be_visible()
        expect(semifinal.get_by_text("本版本尚未创建此轮对抗")).to_be_visible()
        browser.close()


def test_team_knockout_does_not_infer_missing_confirmation():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()

        def route(route):
            if route.request.url.endswith("/api/tournaments/42"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(TOURNAMENT))
            elif route.request.url.endswith("/api/tournaments/42/team-knockout"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(knockout(), ensure_ascii=False))
            elif route.request.url.endswith("/api/tournaments/42/qualification"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(qualification(CONFIRMED_TEAMS), ensure_ascii=False))
            elif route.request.url.endswith("/api/tournaments/42/team-knockout/generate"):
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "A组种子顺序并列，当前版本不支持人工指定淘汰种子顺序"}, ensure_ascii=False))
            else:
                route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-knockout?tid=42")
        expect(page.get_by_text("晋级名单已确认，尚未生成团体淘汰签")).to_be_visible()
        expect(page.get_by_role("link", name="查看晋级确认")).to_be_visible()
        page.get_by_role("button", name="生成首轮淘汰签").click()
        expect(page.get_by_text("A组种子顺序并列，当前版本不支持人工指定淘汰种子顺序")).to_be_visible()
        browser.close()
