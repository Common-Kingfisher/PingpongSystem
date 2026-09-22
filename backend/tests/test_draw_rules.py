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


def test_affiliation_avoidance_prefers_non_colliding_first_round_pairs():
    entries = [_entry(1, "A"), _entry(2, "A"), _entry(3, "B"), _entry(4, "B")]
    affiliations = {entry["id"]: draw.entry_affiliations(entry) for entry in entries}
    for a, b in _first_round_pairs(entries):
        assert not (affiliations[a] & affiliations[b])


def test_doubles_and_missing_affiliations_use_set_intersection_semantics():
    doubles = _entry(1, "A", second_college="B")
    assert draw.entry_affiliations(doubles) == {"A", "B"}
    assert draw.entry_affiliations(_entry(2, "B")) & draw.entry_affiliations(doubles)
    assert draw.entry_affiliations(_entry(3)) == set()


def test_fixed_draw_seed_is_reproducible():
    entries = [_entry(index, "A" if index % 2 else "B") for index in range(1, 9)]
    assert _first_round_pairs(entries, 42) == _first_round_pairs(entries, 42)


@pytest.mark.parametrize("config", [{"unknown": 1}, {"draw_seed": True}, {"draw_seed": "7"}])
def test_rule_config_rejects_unknown_or_invalid_draw_seed(config):
    with pytest.raises(formats.FormatHandlerError):
        formats.validate_rule_config(formats.SINGLE_ELIMINATION, config)


def test_rule_config_accepts_single_elimination_draw_seed_only():
    assert formats.validate_rule_config(formats.SINGLE_ELIMINATION, {"draw_seed": 7}) == {"draw_seed": 7}
