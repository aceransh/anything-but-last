import pytest

from app.trade_math import build_verdict, evaluate_trade


def _p(player_id, position, projected_points):
    return {"player_id": player_id, "position": position, "projected_points": projected_points}


def test_build_verdict_gains():
    assert build_verdict(12.3, threshold=5.0) == "Gains 12.3 pts over the rest of the season"


def test_build_verdict_loses():
    assert build_verdict(-12.3, threshold=5.0) == "Loses 12.3 pts over the rest of the season"


def test_build_verdict_roughly_even_within_threshold():
    assert build_verdict(3.0, threshold=5.0) == "Roughly even trade"
    assert build_verdict(-3.0, threshold=5.0) == "Roughly even trade"


def _team(result, roster_id):
    return next(t for t in result["teams"] if t["roster_id"] == roster_id)


def test_evaluate_trade_two_team_basic_totals_and_differential():
    rosters = {
        1: [_p("wr1", "WR", 100.0), _p("rb1", "RB", 50.0)],
        2: [_p("rb2", "RB", 120.0), _p("qb1", "QB", 200.0)],
    }
    moves = [
        {"player_id": "wr1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "rb2", "from_roster_id": 2, "to_roster_id": 1},
    ]

    result = evaluate_trade(rosters, moves, slot_requirements={"WR": 1, "RB": 1}, threshold=5.0)

    team1 = _team(result, 1)
    team2 = _team(result, 2)
    assert team1["giving_total"] == 100.0
    assert team1["receiving_total"] == 120.0
    assert team1["differential"] == 20.0
    assert team1["verdict"] == "Gains 20.0 pts over the rest of the season"
    assert [p["player_id"] for p in team1["giving_players"]] == ["wr1"]
    assert [p["player_id"] for p in team1["receiving_players"]] == ["rb2"]

    assert team2["giving_total"] == 120.0
    assert team2["receiving_total"] == 100.0
    assert team2["differential"] == -20.0
    assert team2["verdict"] == "Loses 20.0 pts over the rest of the season"


def test_evaluate_trade_multi_player_per_side():
    rosters = {
        1: [_p("wr1", "WR", 60.0), _p("wr2", "WR", 40.0), _p("rb1", "RB", 50.0)],
        2: [_p("rb2", "RB", 80.0), _p("te1", "TE", 30.0)],
    }
    moves = [
        {"player_id": "wr1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "wr2", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "rb2", "from_roster_id": 2, "to_roster_id": 1},
        {"player_id": "te1", "from_roster_id": 2, "to_roster_id": 1},
    ]

    result = evaluate_trade(
        rosters, moves, slot_requirements={"WR": 1, "RB": 1, "TE": 1}, threshold=5.0
    )

    team1 = _team(result, 1)
    assert team1["giving_total"] == 100.0
    assert team1["receiving_total"] == 110.0
    assert team1["differential"] == 10.0


def test_evaluate_trade_three_teams():
    rosters = {
        1: [_p("a1", "WR", 50.0)],
        2: [_p("b1", "RB", 60.0)],
        3: [_p("c1", "QB", 70.0)],
    }
    # A circular 3-team trade: 1 -> 2 -> 3 -> 1.
    moves = [
        {"player_id": "a1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "b1", "from_roster_id": 2, "to_roster_id": 3},
        {"player_id": "c1", "from_roster_id": 3, "to_roster_id": 1},
    ]

    result = evaluate_trade(rosters, moves, slot_requirements={}, threshold=5.0)

    assert len(result["teams"]) == 3
    team1 = _team(result, 1)
    team2 = _team(result, 2)
    team3 = _team(result, 3)
    assert team1["giving_total"] == 50.0 and team1["receiving_total"] == 70.0
    assert team2["giving_total"] == 60.0 and team2["receiving_total"] == 50.0
    assert team3["giving_total"] == 70.0 and team3["receiving_total"] == 60.0


def test_evaluate_trade_raises_for_player_not_on_from_roster():
    with pytest.raises(ValueError, match="not on roster"):
        evaluate_trade(
            rosters={1: [_p("wr1", "WR", 10.0)], 2: [_p("rb2", "RB", 10.0)]},
            moves=[{"player_id": "ghost", "from_roster_id": 1, "to_roster_id": 2}],
            slot_requirements={},
        )


def test_evaluate_trade_raises_for_unknown_roster_in_move():
    with pytest.raises(ValueError, match="not in this trade"):
        evaluate_trade(
            rosters={1: [_p("wr1", "WR", 10.0)], 2: [_p("rb2", "RB", 10.0)]},
            moves=[{"player_id": "wr1", "from_roster_id": 1, "to_roster_id": 99}],
            slot_requirements={},
        )


def test_evaluate_trade_lineup_impact_changes_when_swap_affects_starters():
    rosters = {
        1: [_p("wr1", "WR", 10.0)],
        2: [_p("wr2", "WR", 25.0), _p("wr3", "WR", 5.0)],
    }
    moves = [
        {"player_id": "wr1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "wr2", "from_roster_id": 2, "to_roster_id": 1},
    ]
    slot_requirements = {"WR": 1}

    result = evaluate_trade(rosters, moves, slot_requirements)

    team1 = _team(result, 1)
    team2 = _team(result, 2)
    assert team1["lineup_impact"] == {
        "before_total_projected_points": 10.0,
        "after_total_projected_points": 25.0,
        "change": 15.0,
    }
    assert team2["lineup_impact"] == {
        "before_total_projected_points": 25.0,
        "after_total_projected_points": 10.0,
        "change": -15.0,
    }


def test_evaluate_trade_lineup_impact_unchanged_when_swap_is_bench_only():
    rosters = {
        1: [_p("wr1", "WR", 20.0), _p("wr2", "WR", 15.0), _p("wr3", "WR", 1.0)],
        2: [_p("wr4", "WR", 18.0), _p("wr5", "WR", 12.0), _p("wr6", "WR", 0.5)],
    }
    moves = [
        {"player_id": "wr3", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "wr6", "from_roster_id": 2, "to_roster_id": 1},
    ]
    slot_requirements = {"WR": 2}

    result = evaluate_trade(rosters, moves, slot_requirements)

    assert _team(result, 1)["lineup_impact"]["change"] == 0.0
    assert _team(result, 2)["lineup_impact"]["change"] == 0.0
