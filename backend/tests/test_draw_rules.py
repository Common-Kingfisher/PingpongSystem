import pytest

from app.domain import draw
from app.services import formats


def _entry(entry_id, college=None, *, seed_no=None, second_college=None):
    members = [{"college": college}]
    if second_college is not None:
        members.append({"college": second_college})
    return {"id": entry_id, "seed_no": seed_no, "members": members}


def _first_round_pairs(entries, seed=7):
    return [
        (match["player_a_id"], match["player_b_id"])
        for match in draw.build_single_elimination(entries, draw_seed=seed)[0]
    ]


def test_power_of_two_draw_has_no_bye():
    pairs = _first_round_pairs([_entry(index) for index in range(1, 9)])
    assert all(a is not None and b is not None for a, b in pairs)


def test_non_power_of_two_draw_expresses_byes_as_empty_slots():
    pairs = _first_round_pairs([_entry(index) for index in range(1, 13)])
    assert len(pairs) == 8
    assert sum((a is None) != (b is None) for a, b in pairs) == 4


def test_seed_one_and_two_are_in_different_halves():
    rounds = draw.build_single_elimination([
        _entry(1, seed_no=1), _entry(2, seed_no=2), _entry(3), _entry(4),
    ])
    first_round = rounds[0]
    one = next(match["match_index"] for match in first_round if 1 in (match["player_a_id"], match["player_b_id"]))
    two = next(match["match_index"] for match in first_round if 2 in (match["player_a_id"], match["player_b_id"]))
    assert one != two


@pytest.mark.parametrize("size", [8, 16])
def test_top_two_seeds_are_in_opposite_bracket_halves(size):
    entries = [_entry(1, seed_no=1), _entry(2, seed_no=2)] + [
        _entry(index) for index in range(3, size + 1)
    ]
    first_round = draw.build_single_elimination(entries)[0]
    positions = {
        entry_id: next(
            match["match_index"] for match in first_round
            if entry_id in (match["player_a_id"], match["player_b_id"])
        )
        for entry_id in (1, 2)
    }
    assert (positions[1] < len(first_round) // 2) != (positions[2] < len(first_round) // 2)


def test_seed_and_bye_slots_remain_fixed_when_avoiding_affiliations():
    entries = [_entry(1, "A", seed_no=1), _entry(2, "A", seed_no=2)] + [
        _entry(index, chr(ord("B") + index % 3)) for index in range(3, 13)
    ]
    first_round = draw.build_single_elimination(entries, draw_seed=3)[0]
    seed_matches = {
        entry_id: next(match for match in first_round if entry_id in (match["player_a_id"], match["player_b_id"]))
        for entry_id in (1, 2)
    }

    assert all(None in (match["player_a_id"], match["player_b_id"]) for match in seed_matches.values())
    assert (seed_matches[1]["match_index"] < 4) != (seed_matches[2]["match_index"] < 4)


def test_affiliation_avoidance_prefers_non_colliding_first_round_pairs():
    entries = [_entry(1, "A"), _entry(2, "A"), _entry(3, "B"), _entry(4, "B")]
    affiliations = {entry["id"]: draw.entry_affiliations(entry) for entry in entries}
    for a, b in _first_round_pairs(entries):
        assert not (affiliations[a] & affiliations[b])


def test_affiliation_avoidance_finds_zero_collision_when_feasible():
    entries = [_entry(1, "A"), _entry(2, "B"), _entry(3, "C"), _entry(4, "A")]
    affiliations = {entry["id"]: draw.entry_affiliations(entry) for entry in entries}

    assert all(
        not (affiliations[a] & affiliations[b])
        for a, b in _first_round_pairs(entries, seed=0)
    )


def test_eight_player_draw_finds_zero_collision_when_feasible():
    entries = [_entry(index, chr(ord("A") + (index - 1) % 4)) for index in range(1, 9)]
    affiliations = {entry["id"]: draw.entry_affiliations(entry) for entry in entries}

    assert all(
        not (affiliations[a] & affiliations[b])
        for a, b in _first_round_pairs(entries, seed=0)
    )


def test_doubles_and_missing_affiliations_use_set_intersection_semantics():
    doubles = _entry(1, "A", second_college="B")
    assert draw.entry_affiliations(doubles) == {"A", "B"}
    assert draw.entry_affiliations(_entry(2, "B")) & draw.entry_affiliations(doubles)
    assert draw.entry_affiliations(_entry(3)) == set()


def test_fixed_draw_seed_is_reproducible():
    entries = [_entry(index, "A" if index % 2 else "B") for index in range(1, 9)]
    assert _first_round_pairs(entries, 42) == _first_round_pairs(entries, 42)


def test_unavoidable_collision_keeps_every_entry_exactly_once():
    entries = [_entry(index, "A") for index in range(1, 5)]
    pairs = _first_round_pairs(entries, seed=1)

    assert sorted(entry_id for pair in pairs for entry_id in pair) == [1, 2, 3, 4]
    assert all(draw.entry_affiliations(_entry(a, "A")) & draw.entry_affiliations(_entry(b, "A")) for a, b in pairs)


@pytest.mark.parametrize("config", [{"unknown": 1}, {"draw_seed": True}, {"draw_seed": "7"}])
def test_rule_config_rejects_unknown_or_invalid_draw_seed(config):
    with pytest.raises(formats.FormatHandlerError):
        formats.validate_rule_config(formats.SINGLE_ELIMINATION, config)


def test_rule_config_accepts_single_elimination_draw_seed_only():
    assert formats.validate_rule_config(formats.SINGLE_ELIMINATION, {"draw_seed": 7}) == {"draw_seed": 7}


@pytest.mark.parametrize("format_code", [formats.GROUP_KNOCKOUT, formats.ROUND_ROBIN])
def test_rule_config_accepts_empty_config_for_every_other_supported_format(format_code):
    assert formats.validate_rule_config(format_code, {}) == {}


def test_rule_config_rejects_unknown_format():
    with pytest.raises(formats.UnsupportedFormatError):
        formats.validate_rule_config("UNKNOWN", {})
