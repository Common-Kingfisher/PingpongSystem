"""不依赖 seed/demo 数据的真实浏览器 TEAM 主链。

启动空数据库 FastAPI 与 Vite 后运行；本用例从首页创建赛事，且所有后续写入
都通过页面按钮完成，止于后端生成的团体淘汰首轮。
"""

import os
import time

import pytest
from playwright.sync_api import Page, expect, sync_playwright


pytestmark = pytest.mark.skipif(
    not os.getenv("TEAM_UI_JOURNEY_E2E"),
    reason="需要 TEAM_UI_JOURNEY_E2E=1（空数据库真实后端）",
)


def add_team_with_players(page: Page, name: str) -> None:
    page.get_by_role("button", name="＋ 新建").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("textbox").fill(name)
    dialog.get_by_role("button", name="创建").click()
    for number in (1, 2):
        page.get_by_role("button", name="＋ 新建队员").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("textbox").first.fill(f"{name} 队员 {number}")
        dialog.get_by_role("combobox").select_option(label=name)
        dialog.get_by_role("button", name="加入名单").click()


def play_three_rubbers(page: Page) -> None:
    expect(page.get_by_role("button", name="使用已登记模板初始化对抗")).to_be_visible()
    page.get_by_role("button", name="使用已登记模板初始化对抗").click()
    expect(page.locator(".rubber-card")).to_have_count(5)
    for sequence in (1, 2, 3):
        card = page.locator(".rubber-card").filter(has_text=f"第 {sequence} 盘")
        card.get_by_role("button", name="设置阵容").click()
        choices = page.locator(".lineup-option input")
        choices.nth(0).check()
        choices.nth(2).check()
        if sequence == 3:
            choices.nth(1).check()
            choices.nth(3).check()
        page.get_by_role("button", name="确认阵容").click()
        page.once("dialog", lambda dialog: dialog.accept())
        card.get_by_role("button", name="开始本盘").click()
        card.get_by_role("button", name="录入比分").click()
        page.get_by_label("主队比分").fill("2")
        page.get_by_label("客队比分").fill("0")
        page.get_by_role("button", name="提交比分").click()
    expect(page.get_by_text("团体对抗结束")).to_be_visible()


def test_live_team_ui_journey_to_first_knockout_round() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:5173")
    event_name = f"TEAM 纯 UI 全链 {time.time_ns()}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base_url)
        page.get_by_label("赛事名称").fill(event_name)
        page.get_by_label("小组数量 (1~26)").fill("2")
        page.get_by_label("比赛项目").select_option("TEAM")
        page.get_by_role("button", name="创建赛事").click()
        expect(page.get_by_role("heading", name=f"{event_name} · 队伍与名单")).to_be_visible()

        for name in ("北斗队", "晨星队", "蓝海队", "远山队"):
            add_team_with_players(page, name)
        page.get_by_role("button", name="保存更改").click()
        expect(page.get_by_text("名单已保存", exact=True)).to_be_visible()
        page.get_by_role("button", name="预览确认").click()
        page.get_by_role("button", name="确认并冻结").click()
        expect(page.get_by_text("浏览模式：名单已冻结，修改工具不可用。")).to_be_visible()
        page.get_by_role("button", name="由后端完成分组").click()
        expect(page.get_by_text("分组完成：2 个小组。分组结果由后端计算。")).to_be_visible()
        page.get_by_role("button", name="生成团体小组对抗").click()
        expect(page.get_by_text("已生成 2 场团体小组对抗。")).to_be_visible()
        page.get_by_role("link", name="查看团体对抗").click()
        expect(page.get_by_role("heading", name=f"{event_name} · 团体对抗")).to_be_visible()

        for _ in range(2):
            page.locator(".team-ties-table tr").filter(has=page.locator(".team-tie-status.waiting")).get_by_role("link", name="进入对抗").click()
            play_three_rubbers(page)
            page.get_by_role("link", name="返回对抗列表").click()

        page.get_by_role("link", name="晋级确认").click()
        expect(page.get_by_role("heading", name=f"{event_name} · 晋级确认")).to_be_visible()
        page.get_by_role("button", name="确认后端可自动判定的晋级名单").click()
        page.get_by_role("link", name="进入团体淘汰赛").click()
        page.get_by_role("button", name="生成团体淘汰首轮").click()
        expect(page.get_by_text("首轮已由后端生成。本工作线到此结束，不处理胜者传播。")).to_be_visible()
        browser.close()
