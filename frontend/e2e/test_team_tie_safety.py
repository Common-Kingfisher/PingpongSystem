"""团体对抗操作保护：开始确认、弹窗焦点隔离与禁用原因。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


def rubber(status="READY", *, permissions=None):
    return {
        "id": 7, "team_tie_id": 9, "sequence": 1, "rubber_type": "SINGLES", "status": status,
        "home_slots": ["H1"], "away_slots": ["A1"], "home_player_ids": [101], "away_player_ids": [201],
        "home_players": ["甲一"], "away_players": ["乙一"], "home_score": None, "away_score": None,
        "winner_side": None, "winner_entry_id": None, "match_id": None, "lineup_valid": True,
        "lineup_invalid_reason": None,
        "permissions": permissions or {
            "can_edit_lineup": True, "can_confirm_lineup": True, "can_start": status == "READY",
            "can_record_score": status == "PLAYING", "can_revise_score": False,
        },
        "lineup_options": {
            "home": [{"player_id": 101, "name": "甲一", "available": True, "unavailable_reason": None}],
            "away": [{"player_id": 201, "name": "乙一", "available": True, "unavailable_reason": None}],
        },
        "created_at": "2026-09-19 10:00:00", "started_at": None, "finished_at": None,
    }


def tie(status="WAITING", current_rubber=None):
    return {
        "id": 9, "tournament_id": 42, "stage": "GROUP", "group_id": 1, "round": 1, "match_index": 1,
        "entry_a_id": 1, "entry_b_id": 2, "team_a_score": 0, "team_b_score": 0, "winner_entry_id": None,
        "status": status, "format_code": "TEST", "format_version": 1, "format_snapshot": None,
        "called_at": None, "started_at": None, "finished_at": None, "created_at": "2026-09-19 10:00:00",
        "home_team": {"entry_id": 1, "display_name": "甲队"}, "away_team": {"entry_id": 2, "display_name": "乙队"},
        "home_score": 0, "away_score": 0, "target_wins": 2, "format": {"display_name": "测试赛制"},
        "rubbers": [current_rubber or rubber()],
        "permissions": {"can_edit_lineup": True, "can_confirm_lineup": True, "can_start": True, "can_record_score": False, "can_revise_score": False},
    }


def test_team_tie_protects_start_and_modal_focus():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    started = {"count": 0}
    current_view = {"body": tie()}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()

        def route(route):
            url = route.request.url
            if url.endswith("/api/tournaments/42/team-ties/9"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(current_view["body"], ensure_ascii=False))
            elif url.endswith("/api/tournaments/42/team-ties/9/rubbers/7/start"):
                started["count"] += 1
                route.fulfill(status=200, content_type="application/json", body=json.dumps(tie("PLAYING", rubber("PLAYING")), ensure_ascii=False))
            else:
                route.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base_url}/team-tie?tid=42&tie=9")

        page.once("dialog", lambda dialog: dialog.dismiss())
        page.get_by_role("button", name="开始本盘").click()
        expect(page.get_by_text("可开始")).to_be_visible()
        assert started["count"] == 0

        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="开始本盘").click()
        expect(page.locator(".team-status.playing")).to_be_visible()
        assert started["count"] == 1

        page.reload()
        trigger = page.get_by_role("button", name="设置阵容")
        trigger.click()
        expect(page.locator(".app[inert]")).to_have_count(1)
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Shift+Tab")
        expect(page.get_by_role("button", name="确认阵容")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.get_by_role("button", name="关闭")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        expect(page.locator(".app[inert]")).to_have_count(0)
        expect(trigger).to_be_focused()

        current_view["body"] = tie("PLAYING", rubber("PLAYING"))
        page.reload()
        page.get_by_role("button", name="录入比分").click()
        expect(page.locator(".app[inert]")).to_have_count(1)
        page.keyboard.press("Shift+Tab")
        expect(page.get_by_role("button", name="取消")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.get_by_role("button", name="关闭")).to_be_focused()
        page.get_by_role("button", name="取消").click()
        expect(page.locator(".app[inert]")).to_have_count(0)
        browser.close()


def test_team_tie_explains_disabled_actions():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://localhost:4173")
    locked = rubber("PENDING", permissions={
        "can_edit_lineup": True, "can_confirm_lineup": True, "can_start": False,
        "can_record_score": False, "can_revise_score": False,
    })
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()
        page.route("**/api/tournaments/42/team-ties/9", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(tie(current_rubber=locked), ensure_ascii=False)))
        page.goto(f"{base_url}/team-tie?tid=42&tie=9")
        expect(page.get_by_text("开始本盘：请先提交本盘的合法阵容，再开始比赛")).to_be_visible()
        expect(page.get_by_text("录入比分：请先开始本盘再录分")).to_be_visible()
        browser.close()
