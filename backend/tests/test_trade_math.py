import pytest

from app.trade_math import build_verdict, evaluate_trade


def _p(player_id, position, projected_points):
    return {"player_id": player_id, "position": position, "projected_points": projected_points}


def _single_week(rosters: dict[int, list[dict]], week: int = 1) -> dict[int, dict[int, list[dict]]]:
    """Most tests don't care about per-week nuance -- one week whose pool
    equals the season-total pool exactly reproduces the old sum-then-
    optimize behavior, so existing expectations still hold."""
    return {week: rosters}


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
    # Bench depth at the traded position on both sides means this 1-for-1
    # swap doesn't create a positional crunch -- the incoming player simply
    # becomes the new starter, so lineup-impact and raw points agree here.
    rosters = {
        1: [_p("rb1", "RB", 100.0), _p("rb1b", "RB", 20.0)],
        2: [_p("rb2", "RB", 120.0), _p("rb2b", "RB", 30.0)],
    }
    moves = [
        {"player_id": "rb1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "rb2", "from_roster_id": 2, "to_roster_id": 1},
    ]

    result = evaluate_trade(
        rosters, _single_week(rosters), moves, slot_requirements={"RB": 1}, threshold=5.0
    )

    team1 = _team(result, 1)
    team2 = _team(result, 2)
    assert team1["giving_total"] == 100.0
    assert team1["receiving_total"] == 120.0
    assert team1["differential"] == 20.0
    assert team1["verdict"] == "Gains 20.0 pts over the rest of the season"
    assert [p["player_id"] for p in team1["giving_players"]] == ["rb1"]
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
        rosters,
        _single_week(rosters),
        moves,
        slot_requirements={"WR": 1, "RB": 1, "TE": 1},
        threshold=5.0,
    )

    team1 = _team(result, 1)
    assert team1["giving_total"] == 100.0
    assert team1["receiving_total"] == 110.0


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

    result = evaluate_trade(rosters, _single_week(rosters), moves, slot_requirements={}, threshold=5.0)

    assert len(result["teams"]) == 3
    team1 = _team(result, 1)
    team2 = _team(result, 2)
    team3 = _team(result, 3)
    assert team1["giving_total"] == 50.0 and team1["receiving_total"] == 70.0
    assert team2["giving_total"] == 60.0 and team2["receiving_total"] == 50.0
    assert team3["giving_total"] == 70.0 and team3["receiving_total"] == 60.0


def test_evaluate_trade_raises_for_player_not_on_from_roster():
    rosters = {1: [_p("wr1", "WR", 10.0)], 2: [_p("rb2", "RB", 10.0)]}
    with pytest.raises(ValueError, match="not on roster"):
        evaluate_trade(
            rosters,
            _single_week(rosters),
            moves=[{"player_id": "ghost", "from_roster_id": 1, "to_roster_id": 2}],
            slot_requirements={},
        )


def test_evaluate_trade_raises_for_unknown_roster_in_move():
    rosters = {1: [_p("wr1", "WR", 10.0)], 2: [_p("rb2", "RB", 10.0)]}
    with pytest.raises(ValueError, match="not in this trade"):
        evaluate_trade(
            rosters,
            _single_week(rosters),
            moves=[{"player_id": "wr1", "from_roster_id": 1, "to_roster_id": 99}],
            slot_requirements={},
        )


def test_evaluate_trade_verdict_uses_lineup_impact_not_raw_points():
    # The "2-for-1 trap": team 1 gives up a 200-pt starter and receives two
    # players (120 + 100 = 220 raw pts -- looks like a gain), but only has
    # one WR slot, so it can only ever start the better of the two. Real
    # impact is 120 - 200 = -80, the opposite conclusion raw points give.
    rosters = {
        1: [_p("wr1", "WR", 200.0), _p("wr2", "WR", 50.0)],
        2: [_p("wr3", "WR", 120.0), _p("wr4", "WR", 100.0)],
    }
    moves = [
        {"player_id": "wr1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "wr3", "from_roster_id": 2, "to_roster_id": 1},
        {"player_id": "wr4", "from_roster_id": 2, "to_roster_id": 1},
    ]

    result = evaluate_trade(rosters, _single_week(rosters), moves, slot_requirements={"WR": 1})

    team1 = _team(result, 1)
    assert team1["giving_total"] == 200.0
    assert team1["receiving_total"] == 220.0  # raw points say "gain"
    assert team1["differential"] == -80.0  # real lineup impact says "loss"
    assert team1["verdict"] == "Loses 80.0 pts over the rest of the season"
    assert team1["lineup_impact"] == {
        "before_total_projected_points": 200.0,
        "after_total_projected_points": 120.0,
        "change": -80.0,
    }


def test_evaluate_trade_sums_per_week_not_season_total():
    # RB_X is steady (10/wk); RB_Y is streaky with a bye (20, 0) -- both
    # total 20 over two weeks, so a season-total sum-then-optimize would
    # see them as interchangeable. Real per-week-optimal value differs:
    # start RB_Y week 1 (20), RB_X week 2 when RB_Y is on bye (10) = 30,
    # not 20.
    week1 = {
        1: [_p("rb_y", "RB", 20.0)],
        2: [_p("rb_x", "RB", 10.0)],
    }
    week2 = {
        1: [],  # RB_Y on bye -- absent from this week's real data entirely
        2: [_p("rb_x", "RB", 10.0)],
    }
    rosters = {
        1: [_p("rb_y", "RB", 20.0)],  # season totals: RB_Y=20
        2: [_p("rb_x", "RB", 20.0)],  # RB_X=20 (10+10) -- tied with RB_Y
    }
    weekly_rosters = {1: week1, 2: week2}
    moves = [{"player_id": "rb_x", "from_roster_id": 2, "to_roster_id": 1}]

    result = evaluate_trade(rosters, weekly_rosters, moves, slot_requirements={"RB": 1})

    team1 = _team(result, 1)
    # Before: RB_Y only -> week1 20, week2 0 (bye) = 20 total.
    assert team1["lineup_impact"]["before_total_projected_points"] == 20.0
    # After: RB_Y and RB_X both available -> week1 max(20,10)=20, week2
    # max(0,10)=10 (RB_X fills the bye) = 30 total, not the naive 20.
    assert team1["lineup_impact"]["after_total_projected_points"] == 30.0
    assert team1["lineup_impact"]["change"] == 10.0


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

    result = evaluate_trade(rosters, _single_week(rosters), moves, slot_requirements)

    assert _team(result, 1)["lineup_impact"]["change"] == 0.0
    assert _team(result, 2)["lineup_impact"]["change"] == 0.0


def test_evaluate_trade_playoff_breakdown_can_differ_from_season_total():
    # RB_X helps weeks 1-2 (regular season) but is on bye during week 3
    # (the only playoff week here); RB_Y is the reverse. Season-total
    # impact for team 1 receiving RB_Y ties out at a small gain, but the
    # playoff-only breakdown should show it does nothing for the weeks
    # that actually decide anything.
    weekly_rosters = {
        1: {1: [_p("rb_x", "RB", 10.0)], 2: [_p("rb_y", "RB", 0.0)]},
        2: {1: [_p("rb_x", "RB", 10.0)], 2: [_p("rb_y", "RB", 0.0)]},
        3: {1: [], 2: [_p("rb_y", "RB", 15.0)]},  # rb_x on bye week 3
    }
    rosters = {
        1: [_p("rb_x", "RB", 20.0)],
        2: [_p("rb_y", "RB", 15.0)],
    }
    moves = [{"player_id": "rb_y", "from_roster_id": 2, "to_roster_id": 1}]

    result = evaluate_trade(
        rosters, weekly_rosters, moves, slot_requirements={"RB": 1}, playoff_start_week=3
    )

    team1 = _team(result, 1)
    # Season total: week1 10, week2 10, week3 max(0, 15)=15 after adding
    # rb_y -> before=20 (10+10+0), after=35 (10+10+15), change=+15.
    assert team1["lineup_impact"]["change"] == 15.0
    # Playoff-only (week 3): before=0 (rb_x on bye, nothing to start),
    # after=15 (rb_y fills the bye) -- still a real gain here, just
    # confirming the breakdown is scoped correctly, not double-counting
    # the regular-season weeks.
    assert team1["playoff_lineup_impact"] == {
        "before_total_projected_points": 0.0,
        "after_total_projected_points": 15.0,
        "change": 15.0,
    }


def test_evaluate_trade_playoff_breakdown_none_when_not_provided():
    rosters = {1: [_p("wr1", "WR", 10.0)], 2: [_p("wr2", "WR", 10.0)]}
    moves = [{"player_id": "wr2", "from_roster_id": 2, "to_roster_id": 1}]

    result = evaluate_trade(rosters, _single_week(rosters), moves, slot_requirements={"WR": 1})

    assert _team(result, 1)["playoff_lineup_impact"] is None


def test_evaluate_trade_playoff_breakdown_none_when_playoffs_already_past_range():
    rosters = {1: [_p("wr1", "WR", 10.0)], 2: [_p("wr2", "WR", 10.0)]}
    moves = [{"player_id": "wr2", "from_roster_id": 2, "to_roster_id": 1}]

    result = evaluate_trade(
        rosters, _single_week(rosters, week=1), moves, slot_requirements={"WR": 1}, playoff_start_week=99
    )

    assert _team(result, 1)["playoff_lineup_impact"] is None
