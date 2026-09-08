"""人工晋级裁定页面验收：候选限制、必填信息与提交后的审计展示。"""

import json
import os

from playwright.sync_api import expect, sync_playwright


TOURNAMENT = {
    "id": 42, "name": "人工裁定页面测试", "date": "2026-09-08",
    "table_count": 2, "group_count": 1, "qualify_per_group": 1,
    "stage": "GROUP_STAGE", "created_at": "2026-09-08 10:00:00",
    "event_type": "SINGLES", "bronze_mode": "JOINT_BRONZE",
    "placement_mode": "OFF", "games_to_win": 2, "points_to_win": 11,
    "roster_confirmed": True, "confirmed_at": "2026-09-08 10:01:00",
}


def _ranking(resolved: bool = False) -> dict:
    decision = {
        "id": 7, "tournament_id": 42, "group_id": 3,
        "selected_entry_ids": [11], "reason": "组委会现场抽签",
        "operator_name": "裁判长", "created_at": "2026-09-08 12:00:00",
        "invalidated_at": None, "invalidation_reason": None, "active": True,
    } if resolved else None
    entries = []
    for entry_id, name in ((11, "甲"), (12, "乙"), (13, "丙")):
        entries.append({
            "player_id": entry_id, "entry_id": entry_id, "name": name,
            "wins": 1, "losses": 1, "games_won": 2, "games_lost": 2,
            "rank": 1, "tied": True, "qualified": resolved and entry_id == 11,
            "match_points": 3, "points_won": 32, "points_lost": 32,
            "point_difference": 0, "point_ratio": 1,
        })
    return {"rankings": [{
        "group_id": 3, "group_name": "A组", "qualify_count": 1,
        "total_matches": 3, "finished_matches": 3,
        "ambiguous_qualification": not resolved, "needs_point_scores": False,
        "point_score_match_ids": [], "manually_resolved": resolved,
        "manual_candidate_entry_ids": [11, 12, 13], "manual_slots_remaining": 1,
        "qualification_decision": decision, "entries": entries,
    }]}


def test_manual_qualification_dialog_and_record() -> None:
    base_url = os.getenv("PINGPONG_E2E_URL", "http://127.0.0.1:4173")
    resolved = {"value": False}
    submitted = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel=os.getenv("PLAYWRIGHT_CHANNEL", "msedge"), headless=True
        )
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.route("**/api/tournaments/42", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(TOURNAMENT, ensure_ascii=False)
        ))
        page.route("**/api/tournaments/42/matches**", lambda route: route.fulfill(
            status=200, content_type="application/json", body="[]"
        ))

        def rankings_route(route):
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_ranking(resolved["value"]), ensure_ascii=False),
            )

        def decision_route(route):
            submitted.update(route.request.post_data_json)
            resolved["value"] = True
            route.fulfill(
                status=201, content_type="application/json",
                body=json.dumps(_ranking(True)["rankings"][0]["qualification_decision"], ensure_ascii=False),
            )

        page.route("**/api/tournaments/42/rankings", rankings_route)
        page.route("**/api/tournaments/42/groups/3/qualification-decision", decision_route)
        page.goto(f"{base_url}/rankings?tid=42")
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="主裁判人工裁定").click()
        expect(page.get_by_role("heading", name="A组 · 人工指定晋级")).to_be_visible()
        confirm = page.get_by_role("button", name="确认并记录裁定")
        expect(confirm).to_be_disabled()
        page.locator(".decision-candidate-list label").filter(has_text="甲").click()
        page.get_by_label("裁定理由").fill("组委会现场抽签")
        page.get_by_label("操作者（主裁判）").fill("裁判长")
        expect(confirm).to_be_enabled()
        confirm.click()

        expect(page.get_by_text("已由主裁判完成人工裁定")).to_be_visible()
        expect(page.get_by_text("裁定晋级", exact=False)).to_be_visible()
        assert submitted["selected_entry_ids"] == [11]
        assert submitted["operator_name"] == "裁判长"
        browser.close()


if __name__ == "__main__":
    test_manual_qualification_dialog_and_record()
