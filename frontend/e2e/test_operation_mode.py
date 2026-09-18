"""正式/演示模式浏览器验收：标识、演示入口和后端强制边界。"""

import os
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def _create(page, name: str, mode: str) -> None:
    page.get_by_label("赛事名称").fill(name)
    page.get_by_label("运行模式").select_option(mode)
    page.get_by_role("button", name="创建赛事").click()
    expect(page.locator(".current-event-card").get_by_role("heading")).to_contain_text(name)


def _open_players(page) -> int:
    page.locator(".current-event-card").get_by_role("link", name="选手与分组").click()
    page.wait_for_load_state("networkidle")
    return int(parse_qs(urlparse(page.url).query)["tid"][0])


def test_operation_mode_boundaries() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:5174")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True
        )
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        _create(page, "浏览器演示模式测试", "DEMO")
        demo_id = _open_players(page)
        expect(page.get_by_text("演示赛事", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Demo 生成演示选手")).to_be_visible()
        expect(page.get_by_role("button", name="Excel / CSV 导入")).to_be_visible()

        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        _create(page, "浏览器正式模式测试", "LIVE")
        live_id = _open_players(page)
        expect(page.get_by_text("正式赛事", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Demo 生成演示选手")).to_have_count(0)
        # 名单导入是正式能力：LIVE 赛事必须能看到导入入口
        expect(page.get_by_role("button", name="Excel / CSV 导入")).to_be_visible()

        rejected = page.request.post(
            f"{base_url}/api/tournaments/{live_id}/demo/generate-players",
            data={"count": 8, "with_seeds": True},
        )
        assert rejected.status == 409
        assert rejected.json()["detail"] == "正式赛事禁止使用演示数据功能"

        allowed = page.request.post(
            f"{base_url}/api/tournaments/{demo_id}/demo/generate-players",
            data={"count": 8, "with_seeds": True},
        )
        assert allowed.status == 200
        browser.close()


if __name__ == "__main__":
    test_operation_mode_boundaries()
