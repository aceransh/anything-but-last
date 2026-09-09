import pytest

from app.lineup_math import (
    build_alternate_lineup,
    build_context_aware_lineup,
    build_slot_requirements,
    classify_unresolved_players,
    compute_context_weight,
    context_aware_score,
    detect_same_team_stacks,
    is_injury_warning,
    optimize_lineup,
)

# Real roster_positions verified live against Sleeper for the league used
# in manual end-to-end testing (league 1389388817651236864).
REAL_ROSTER_POSITIONS = [
    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF",
    "BN", "BN", "BN", "BN", "BN", "BN",
]


def test_build_slot_requirements_tallies_real_league():
    assert build_slot_requirements(REAL_ROSTER_POSITIONS) == {
        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1,
    }


def test_build_slot_requirements_ignores_bench_and_unknown_slots():
    result = build_slot_requirements(["QB", "BN", "BN", "IR", "TAXI"])
    assert result == {"QB": 1}


def _player(player_id, position, projected_points):
    return {"player_id": player_id, "position": position, "projected_points": projected_points}


def test_optimize_lineup_full_roster():
    players = [
        _player("qb1", "QB", 20),
        _player("qb2", "QB", 15),
        _player("rb1", "RB", 18),
        _player("rb2", "RB", 14),
        _player("rb3", "RB", 12),  # should win FLEX over wr3/te2
        _player("wr1", "WR", 16),
        _player("wr2", "WR", 13),
        _player("wr3", "WR", 9),
        _player("te1", "TE", 11),
        _player("te2", "TE", 8),
        _player("k1", "K", 7),
        _player("def1", "DEF", 6),
    ]
    slot_requirements = build_slot_requirements(REAL_ROSTER_POSITIONS)

    result = optimize_lineup(players, slot_requirements)

    starter_ids_by_slot = {p["player_id"]: p["slot"] for p in result["starters"]}
    assert starter_ids_by_slot == {
        "qb1": "QB",
        "rb1": "RB", "rb2": "RB",
        "wr1": "WR", "wr2": "WR",
        "te1": "TE",
        "k1": "K",
        "def1": "DEF",
        "rb3": "FLEX",
    }
    bench_ids = {p["player_id"] for p in result["bench"]}
    assert bench_ids == {"qb2", "wr3", "te2"}
    assert result["total_projected_points"] == 20 + 18 + 14 + 16 + 13 + 11 + 7 + 6 + 12


def test_optimize_lineup_handles_missing_position_entirely():
    # No kicker on the roster at all -- shouldn't crash, K slot just goes
    # unfilled.
    players = [_player("qb1", "QB", 20), _player("def1", "DEF", 6)]
    slot_requirements = {"QB": 1, "K": 1, "DEF": 1}

    result = optimize_lineup(players, slot_requirements)

    assert {p["player_id"] for p in result["starters"]} == {"qb1", "def1"}
    assert result["bench"] == []


def test_optimize_lineup_carries_extra_fields_through():
    players = [{"player_id": "qb1", "position": "QB", "projected_points": 20, "name": "Test QB"}]
    result = optimize_lineup(players, {"QB": 1})
    assert result["starters"][0]["name"] == "Test QB"


def _pc(player_id, position, projected_points, team):
    return {"player_id": player_id, "position": position, "projected_points": projected_points, "team": team}


def test_detect_same_team_stacks_flags_wr_wr():
    starters = [_pc("wr_a", "WR", 14.0, "CAR"), _pc("wr_b", "WR", 12.1, "CAR")]
    assert detect_same_team_stacks(starters) == [("wr_a", "wr_b")]


def test_detect_same_team_stacks_flags_wr_te():
    starters = [_pc("wr_a", "WR", 14.0, "CAR"), _pc("te_a", "TE", 9.0, "CAR")]
    assert detect_same_team_stacks(starters) == [("wr_a", "te_a")]


def test_detect_same_team_stacks_ignores_different_teams():
    starters = [_pc("wr_a", "WR", 14.0, "CAR"), _pc("wr_b", "WR", 12.1, "DAL")]
    assert detect_same_team_stacks(starters) == []


def test_detect_same_team_stacks_ignores_te_te_and_rb_pairs():
    starters = [
        _pc("te_a", "TE", 9.0, "CAR"),
        _pc("te_b", "TE", 6.0, "CAR"),
        {"player_id": "rb_a", "position": "RB", "projected_points": 10.0, "team": "CAR"},
        {"player_id": "rb_b", "position": "RB", "projected_points": 8.0, "team": "CAR"},
    ]
    assert detect_same_team_stacks(starters) == []


def test_build_alternate_lineup_swaps_lower_scorer_for_bench_alternative():
    players = [
        _pc("wr_a", "WR", 14.0, "CAR"),
        _pc("wr_b", "WR", 12.1, "CAR"),  # lower of the CAR pair -- should get swapped out
        _pc("wr_bench", "WR", 11.9, "NE"),  # next-best alternative
    ]
    slot_requirements = {"WR": 2}
    primary = optimize_lineup(players, slot_requirements)
    stacks = detect_same_team_stacks(primary["starters"])
    assert stacks == [("wr_a", "wr_b")]

    alt = build_alternate_lineup(players, slot_requirements, stacks)

    assert alt is not None
    alt_starter_ids = {p["player_id"] for p in alt["starters"]}
    assert alt_starter_ids == {"wr_a", "wr_bench"}
    assert alt["swapped_out"] == ["wr_b"]
    # The swapped-out player is benched, not dropped from the roster
    # entirely -- a real bug caught by manual testing before this test
    # existed.
    assert {p["player_id"] for p in alt["bench"]} == {"wr_b"}


def test_build_alternate_lineup_returns_none_when_no_stacks():
    assert build_alternate_lineup([], {}, []) is None


def test_is_injury_warning_flags_out_and_similar_statuses():
    for status in ("Out", "Doubtful", "IR", "PUP", "Suspended"):
        assert is_injury_warning(status) is True


def test_is_injury_warning_excludes_questionable_and_none():
    assert is_injury_warning("Questionable") is False
    assert is_injury_warning(None) is False


def test_classify_unresolved_players_confirms_def_bye_from_team_code():
    # KC's real 2026 bye is week 5 (bye_weeks.py) -- a DEF's player_id is
    # literally its team code, so this needs no roster/network lookup.
    result = classify_unresolved_players(["KC"], "2026", 5)
    assert result == [{"player_id": "KC", "reason": "bye"}]


def test_classify_unresolved_players_def_not_on_bye_falls_back():
    # KC isn't on bye in week 1 -- an unresolved DEF here is unexpected,
    # but should degrade to "no_projection" rather than a wrong "bye".
    result = classify_unresolved_players(["KC"], "2026", 1)
    assert result == [{"player_id": "KC", "reason": "no_projection"}]


def _player_fc(player_id, position, projected_points, floor_points, ceiling_points):
    return {
        "player_id": player_id,
        "position": position,
        "projected_points": projected_points,
        "floor_points": floor_points,
        "ceiling_points": ceiling_points,
    }


def test_compute_context_weight_at_named_fixed_points():
    assert compute_context_weight(0.40) == 1.0
    assert compute_context_weight(0.65) == 0.0


def test_compute_context_weight_clamps_outside_the_band():
    assert compute_context_weight(0.10) == 1.0
    assert compute_context_weight(0.90) == 0.0


def test_compute_context_weight_interpolates_linearly_in_the_band():
    assert compute_context_weight(0.525) == pytest.approx(0.5)


def test_context_aware_score_favors_ceiling_when_underdog():
    # Same mean, but rb_boom has more upside -- at w=1 (full underdog) it
    # should score higher than the steadier rb_safe.
    rb_boom = _player_fc("boom", "RB", 15.0, floor_points=5.0, ceiling_points=35.0)
    rb_safe = _player_fc("safe", "RB", 15.0, floor_points=13.0, ceiling_points=17.0)
    assert context_aware_score(rb_boom, 1.0) > context_aware_score(rb_safe, 1.0)


def test_context_aware_score_favors_floor_when_favorite():
    rb_boom = _player_fc("boom", "RB", 15.0, floor_points=5.0, ceiling_points=35.0)
    rb_safe = _player_fc("safe", "RB", 15.0, floor_points=13.0, ceiling_points=17.0)
    assert context_aware_score(rb_safe, 0.0) > context_aware_score(rb_boom, 0.0)


def test_context_aware_score_no_real_data_is_flat_double():
    player = _player("rb1", "RB", 15.0)
    assert context_aware_score(player, 0.5) == 30.0
    assert context_aware_score(player, 1.0) == 30.0
    assert context_aware_score(player, 0.0) == 30.0


def test_build_context_aware_lineup_picks_high_ceiling_when_underdog():
    players = [
        _player_fc("boom", "RB", 15.0, floor_points=5.0, ceiling_points=35.0),
        _player_fc("safe", "RB", 15.0, floor_points=13.0, ceiling_points=17.0),
    ]
    result = build_context_aware_lineup(players, {"RB": 1}, w_context=1.0)
    assert [p["player_id"] for p in result["starters"]] == ["boom"]
    assert result["w_context"] == 1.0
    # total_projected_points reports real E[Y] of the chosen starter, not
    # the adjusted context score.
    assert result["total_projected_points"] == 15.0


def test_build_context_aware_lineup_picks_high_floor_when_favorite():
    players = [
        _player_fc("boom", "RB", 15.0, floor_points=5.0, ceiling_points=35.0),
        _player_fc("safe", "RB", 15.0, floor_points=13.0, ceiling_points=17.0),
    ]
    result = build_context_aware_lineup(players, {"RB": 1}, w_context=0.0)
    assert [p["player_id"] for p in result["starters"]] == ["safe"]


def test_classify_unresolved_players_skill_position_id_is_no_projection():
    # A real Sleeper skill-position player_id (numeric string), not a
    # team code -- can't be confirmed as a bye without the full player
    # list, so it falls back to the generic reason.
    result = classify_unresolved_players(["4046"], "2026", 5)
    assert result == [{"player_id": "4046", "reason": "no_projection"}]
