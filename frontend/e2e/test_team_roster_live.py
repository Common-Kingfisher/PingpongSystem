"""真实前后端名单工作表联调：由 run_team_roster_demo.py 提供独立数据。"""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


TID = os.getenv("TEAM_ROSTER_E2E_TID")
pytestmark = pytest.mark.skipif(not TID, reason="需要 TEAM_ROSTER_E2E_TID")


def test_live_team_roster_assigns_and_confirms() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:5173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/team-roster?tid={TID}")

        expect(page.get_by_role("heading", name="队伍名单工作表测试场 · 队伍与名单")).to_be_visible()
        page.get_by_label("待分队一 所属队伍").select_option(label="蓝海队")
        page.get_by_label("待分队二 所属队伍").select_option(label="晨星队")
        expect(page.get_by_role("button", name="保存更改")).to_be_enabled()
        page.get_by_role("button", name="保存更改").click()
        expect(page.get_by_text("名单已保存", exact=True)).to_be_visible()
        expect(page.get_by_label("待分队一 所属队伍").locator("option:checked")).to_have_text("蓝海队")
        expect(page.get_by_label("待分队二 所属队伍").locator("option:checked")).to_have_text("晨星队")
        page.get_by_role("button", name="预览确认").click()
        expect(page.get_by_role("heading", name="名单预览确认")).to_be_visible()
        expect(page.get_by_role("button", name="确认并冻结")).to_be_enabled()
        page.get_by_role("button", name="确认并冻结").click()
        expect(page.get_by_text("浏览模式：名单已冻结，修改工具不可用。")).to_be_visible()
        expect(page.get_by_role("button", name="＋ 新建队员")).to_be_disabled()
        browser.close()
