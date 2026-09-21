"""真实前后端晋级确认与淘汰签联调。"""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


TID = os.getenv("TEAM_QUALIFICATION_KNOCKOUT_E2E_TID")
pytestmark = pytest.mark.skipif(not TID, reason="需要 TEAM_QUALIFICATION_KNOCKOUT_E2E_TID")


def test_live_team_qualification_then_knockout() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:5173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/team-qualification?tid={TID}")

        expect(page.get_by_role("heading", name="团体晋级淘汰签真实联调场 · 晋级确认")).to_be_visible()
        expect(page.get_by_text("名次已确定")).to_have_count(4)
        page.get_by_role("button", name="确认晋级名单").click()
        expect(page.get_by_role("heading", name="已确认队伍")).to_be_visible()
        expect(page.get_by_role("list").filter(has_text="联调队").get_by_role("listitem")).to_have_count(8)
        page.get_by_role("link", name="前往团体淘汰签").click()

        expect(page.get_by_role("heading", name="团体晋级淘汰签真实联调场 · 团体淘汰签")).to_be_visible()
        expect(page.get_by_text("晋级名单已确认，尚未生成团体淘汰签")).to_be_visible()
        page.get_by_role("button", name="生成首轮淘汰签").click()
        expect(page.get_by_role("heading", name="Quarter Final")).to_be_visible()
        expect(page.get_by_role("heading", name="Semi Final")).to_be_visible()
        expect(page.get_by_role("heading", name="Final", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="进入对抗")).to_have_count(4)
        expect(page.get_by_text("待上游胜者")).to_have_count(3)
        browser.close()
