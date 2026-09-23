"""V0.3 Day 1 保留的赛制与抽签契约；比分、改分、排名已迁移至正式行为测试。"""

import pytest

@pytest.mark.parametrize(
    "format_code",
    ["ROUND_ROBIN", "SINGLE_ELIMINATION"],
)
def test_format_handler_contract_scenarios(format_code):
    """每种 Day4 Handler 均落实统一六方法契约。"""
    from app.services import formats

    handler = formats.resolve_format_handler(format_code)
    assert handler.format_code == format_code
    assert all(callable(getattr(handler, method)) for method in (
        "validate_config", "generate_matches", "calculate_ranking",
        "advance_participants", "handle_bye", "get_completion_state",
    ))


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("power_of_two", "2 的幂人数无 BYE"),
        ("non_power_of_two", "非 2 的幂人数以 BYE 结构表达"),
        ("seed_protection", "种子保护优先于单位规避"),
        ("affiliation_avoidance", "在可行范围内减少同单位碰撞"),
        ("unavoidable_collision", "无法完全规避时保持赛制合法且可解释"),
        ("doubles_affiliations", "双打任一 affiliation 相交即为冲突"),
        ("missing_affiliation", "缺失 affiliation 不制造虚假冲突"),
        ("reproducible_seed", "固定随机种子得到可复现签表"),
    ],
)
def test_draw_contract_scenarios(scenario, expected):
    """每个 Day4 抽签反例都直接检查签位/单位集合的不变量。"""
    from app.domain import draw
    entries = [
        {"id": 1, "seed_no": 1, "members": [{"college": "A"}]},
        {"id": 2, "seed_no": 2, "members": [{"college": "A"}]},
        {"id": 3, "seed_no": None, "members": [{"college": "B"}]},
        {"id": 4, "seed_no": None, "members": [{"college": "B"}]},
    ]
    pairs = draw.build_single_elimination(entries, draw_seed=11)[0]
    if scenario == "power_of_two":
        assert all(match["player_a_id"] is not None and match["player_b_id"] is not None for match in pairs)
    elif scenario == "non_power_of_two":
        byes = draw.build_single_elimination(entries[:3], draw_seed=11)[0]
        assert sum((match["player_a_id"] is None) != (match["player_b_id"] is None) for match in byes) == 1
    elif scenario == "seed_protection":
        seeded = entries[:2] + [
            {"id": index, "seed_no": None, "members": [{"college": "C"}]}
            for index in range(3, 9)
        ]
        first_round = draw.build_single_elimination(seeded, draw_seed=11)[0]
        seed_matches = {
            entry_id: next(
                match["match_index"] for match in first_round
                if entry_id in (match["player_a_id"], match["player_b_id"])
            )
            for entry_id in (1, 2)
        }
        assert (seed_matches[1] < len(first_round) // 2) != (seed_matches[2] < len(first_round) // 2)
    elif scenario == "affiliation_avoidance":
        entries = [
            {"id": 1, "seed_no": None, "members": [{"college": "A"}]},
            {"id": 2, "seed_no": None, "members": [{"college": "B"}]},
            {"id": 3, "seed_no": None, "members": [{"college": "C"}]},
            {"id": 4, "seed_no": None, "members": [{"college": "A"}]},
        ]
        affiliations = {entry["id"]: draw.entry_affiliations(entry) for entry in entries}
        pairs = draw.build_single_elimination(entries, draw_seed=0)[0]
        assert all(not (affiliations[a] & affiliations[b]) for a, b in (
            (match["player_a_id"], match["player_b_id"]) for match in pairs
        ))
    elif scenario == "unavoidable_collision":
        same = [{"id": index, "seed_no": None, "members": [{"college": "A"}]} for index in range(1, 5)]
        first_round = draw.build_single_elimination(same, draw_seed=11)[0]
        assert len(first_round) == 2
        assert sorted(entry_id for match in first_round for entry_id in (
            match["player_a_id"], match["player_b_id"]
        )) == [1, 2, 3, 4]
    elif scenario == "doubles_affiliations":
        assert draw.entry_affiliations({"members": [{"college": "A"}, {"college": "B"}]}) == {"A", "B"}
    elif scenario == "missing_affiliation":
        assert draw.entry_affiliations({"members": [{"college": None}]}) == set()
    elif scenario == "reproducible_seed":
        assert draw.build_single_elimination(entries, 11) == draw.build_single_elimination(entries, 11)
    else:  # pragma: no cover - 参数化场景必须显式实现
        raise AssertionError(f"未覆盖的抽签场景：{scenario} — {expected}")
