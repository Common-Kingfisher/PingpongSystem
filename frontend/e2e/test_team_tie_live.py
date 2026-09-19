"""真实前后端团体赛联调：由 run_team_tie_demo.py 提供独立种子数据。"""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


TID = os.getenv("TEAM_TIE_E2E_TID")
TIE_ID = os.getenv("TEAM_TIE_E2E_TIE_ID")
pytestmark = pytest.mark.skipif(not (TID and TIE_ID), reason="需要 TEAM_TIE_E2E_TID 与 TEAM_TIE_E2E_TIE_ID")


def test_live_team_tie_flow() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:5173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/team-ties?tid={TID}")
        expect(page.get_by_role("heading", name="团体对抗真实联调场 · 团体对抗")).to_be_visible()
        expect(page.locator(".team-ties-section").filter(has_text="A组")).to_be_visible()
        page.goto(f"{base_url}/team-tie?tid={TID}&tie={TIE_ID}")

        for sequence, home_score, away_score, players_per_side in ((1, 2, 0, 1), (2, 0, 2, 1), (3, 2, 1, 2), (4, 2, 0, 1)):
            card = page.locator(".rubber-card").filter(has_text=f"第 {sequence} 盘")
            card.get_by_role("button", name="设置阵容").click()
            choices = page.locator(".lineup-option input")
            for index in range(players_per_side):
                choices.nth(index).check()
                choices.nth(4 + index).check()
            page.get_by_role("button", name="确认阵容").click()
            page.once("dialog", lambda dialog: dialog.accept())
            card.get_by_role("button", name="开始本盘").click()
            card.get_by_role("button", name="录入比分").click()
            page.get_by_label("主队比分").fill(str(home_score))
            page.get_by_label("客队比分").fill(str(away_score))
            page.get_by_role("button", name="提交比分").click()

        expect(page.get_by_text("团体对抗结束")).to_be_visible()
        expect(page.get_by_text("3 : 1", exact=True)).to_be_visible()
        skipped = page.locator(".rubber-card").filter(has_text="第 5 盘")
        expect(skipped.get_by_text("不再进行", exact=True)).to_be_visible()
        expect(skipped.get_by_role("button", name="设置阵容")).to_be_disabled()
        expect(skipped.get_by_role("button", name="开始本盘")).to_be_disabled()
        expect(skipped.get_by_role("button", name="录入比分")).to_be_disabled()
        expect(skipped.get_by_role("status")).to_contain_text("本盘因对抗已提前结束而跳过，不能设置阵容")
        page.get_by_role("link", name="返回对抗列表").click()
        expect(page.get_by_text("3 : 1", exact=True)).to_be_visible()
        page.goto(f"{base_url}/team-rankings?tid={TID}")
        expect(page.get_by_role("heading", name="团体对抗真实联调场 · 团体排名")).to_be_visible()
        blue_sea = page.locator(".team-standings-table tbody tr").filter(has_text="蓝海队")
        expect(blue_sea).to_contain_text("3:1")
        expect(blue_sea).to_contain_text("晋级线内")
        browser.close()
