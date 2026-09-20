"""团体赛名单工作表的浏览器验收：Excel 式表格、预览冻结和只读态。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


def tournament(confirmed=False):
    return {
        "id": 42, "name": "秋季团体赛", "date": "2026-09-19", "table_count": 2,
        "group_count": 1, "qualify_per_group": 1, "stage": "REGISTRATION",
        "created_at": "2026-09-19 09:00:00", "event_type": "TEAM",
        "bronze_mode": "JOINT_BRONZE", "placement_mode": "OFF", "games_to_win": 2,
        "points_to_win": 11, "roster_confirmed": confirmed,
        "confirmed_at": "2026-09-19 10:00:00" if confirmed else None, "operation_mode": "LIVE",
    }


def team(team_id, name, members, order):
    return {
        "id": team_id, "tournament_id": 42, "entry_type": "TEAM", "display_name": name,
        "rating_points": 0, "sort_order": order, "group_id": None, "seed_no": None,
        "status": "ACTIVE", "withdrawn_at": None, "withdrawn_by": None, "withdrawal_reason": None,
        "members": members,
    }


def member(player_id, name, order):
    return {"player_id": player_id, "name": name, "college": "体育学院", "rating_points": 1000, "member_order": order}


def sheet(confirmed=False):
    return {
        "tournament": tournament(confirmed),
        "teams": [team(1, "甲队", [member(1, "张三", 1), member(2, "李四", 2)], 1), team(2, "乙队", [member(3, "王五", 1), member(4, "赵六", 2)], 2)],
        "players": [
            {"id": 1, "tournament_id": 42, "name": "张三", "college": "体育学院", "group_id": None, "seed_no": None, "rating_points": 1000},
            {"id": 2, "tournament_id": 42, "name": "李四", "college": "体育学院", "group_id": None, "seed_no": None, "rating_points": 1000},
            {"id": 3, "tournament_id": 42, "name": "王五", "college": "体育学院", "group_id": None, "seed_no": None, "rating_points": 1000},
            {"id": 4, "tournament_id": 42, "name": "赵六", "college": "体育学院", "group_id": None, "seed_no": None, "rating_points": 1000},
        ], "revision": "revision-1",
    }


def test_team_roster_preview_freezes_editor():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:4173")
    state = {"confirmed": False, "saves": 0, "save_payload": None}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        def roster(route):
            if route.request.method == "PUT":
                state["saves"] += 1
                state["save_payload"] = route.request.post_data_json
            route.fulfill(status=200, content_type="application/json", body=json.dumps(sheet(state["confirmed"]), ensure_ascii=False))

        page.route("**/api/tournaments/42/team-roster", roster)
        page.route("**/api/tournaments/42/confirm-roster", lambda route: (state.update(confirmed=True), route.fulfill(status=200, content_type="application/json", body=json.dumps({"tournament": tournament(True), "entries": []}, ensure_ascii=False))))
        page.goto(f"{base_url}/team-roster?tid=42")

        expect(page.get_by_role("heading", name="秋季团体赛 · 队伍与名单")).to_be_visible()
        expect(page.locator(".roster-grid tbody tr")).to_have_count(4)
        expect(page.get_by_role("button", name="撤销冻结")).to_be_disabled()
        page.get_by_label("选择 张三").focus()
        page.keyboard.press("Space")
        expect(page.locator(".roster-grid tbody tr.selected")).to_have_count(1)
        page.get_by_label("张三 姓名").fill("张三丰")
        expect(page.get_by_role("button", name="保存更改")).to_be_enabled()
        page.get_by_role("button", name="保存更改").click()
        assert state["saves"] == 1
        assert state["save_payload"]["players"][0]["name"] == "张三丰"
        page.get_by_role("button", name="预览确认").click()
        expect(page.get_by_role("heading", name="名单预览确认")).to_be_visible()
        page.get_by_role("button", name="确认并冻结").click()
        expect(page.get_by_text("浏览模式：名单已冻结，修改工具不可用。")).to_be_visible()
        expect(page.get_by_role("button", name="＋ 新建队员")).to_be_disabled()
        expect(page.get_by_role("button", name="预览名单")).to_be_enabled()
        page.get_by_role("button", name="预览名单").click()
        expect(page.get_by_role("heading", name="名单预览")).to_be_visible()
        expect(page.get_by_role("button", name="名单已冻结")).to_be_disabled()
        browser.close()


def test_team_roster_warns_before_leaving_unsaved_draft():
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:4173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page()
        page.route("**/api/tournaments/42/team-roster", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(sheet(), ensure_ascii=False)))
        page.route("**/api/tournaments/42", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(tournament(), ensure_ascii=False)))
        page.goto(f"{base_url}/team-roster?tid=42")
        page.get_by_label("张三 姓名").fill("张三丰")

        page.once("dialog", lambda dialog: dialog.dismiss())
        page.locator(".roster-title-actions a").click()
        expect(page).to_have_url(f"{base_url}/team-roster?tid=42")

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator(".roster-title-actions a").click()
        expect(page).to_have_url(f"{base_url}/team-ties?tid=42")

        page.goto(f"{base_url}/team-roster?tid=42")
        page.get_by_label("张三 姓名").fill("张三丰")

        page.once("dialog", lambda dialog: dialog.dismiss())
        page.locator("nav").get_by_role("link", name="团体对抗").click()
        expect(page).to_have_url(f"{base_url}/team-roster?tid=42")

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("nav").get_by_role("link", name="团体对抗").click()
        expect(page).to_have_url(f"{base_url}/team-ties?tid=42")
        browser.close()
