import numpy as np
import pytest

from app.matchup_math import (
    CEILING_Z,
    build_correlation_matrix,
    player_std_dev,
    simulate_matchup,
    simulate_scores,
    simulate_season,
    weekly_std_dev,
)


def _p(player_id, position, projected_points, team=None):
    return {"player_id": player_id, "position": position, "projected_points": projected_points, "team": team}


def _rng():
    return np.random.default_rng(seed=0)


def test_weekly_std_dev_zero_projection_is_zero():
    assert weekly_std_dev("RB", 0.0) == 0.0
    assert weekly_std_dev("RB", -5.0) == 0.0


def test_player_std_dev_uses_real_floor_ceiling_when_present():
    player = {"position": "RB", "projected_points": 20.0, "floor_points": 10.0, "ceiling_points": 30.0}
    assert player_std_dev(player) == pytest.approx((30.0 - 10.0) / (2 * CEILING_Z))


def test_player_std_dev_falls_back_to_synthetic_proxy_without_real_data():
    player = {"position": "RB", "projected_points": 20.0}
    assert player_std_dev(player) == weekly_std_dev("RB", 20.0)


def test_weekly_std_dev_wr_gets_discount():
    rb_pct = weekly_std_dev("RB", 100.0) / 100.0
    wr_pct = weekly_std_dev("WR", 100.0) / 100.0
    assert wr_pct < rb_pct
    assert rb_pct == pytest.approx(0.12)
    assert wr_pct == pytest.approx(0.09)


def test_build_correlation_matrix_qb_wr_stack_is_positive():
    players = [_p("qb1", "QB", 20.0, "KC"), _p("wr1", "WR", 15.0, "KC")]
    corr = build_correlation_matrix(players)
    assert corr[0, 1] == corr[1, 0] == pytest.approx(0.45)


def test_build_correlation_matrix_qb_te_stack_is_positive():
    players = [_p("qb1", "QB", 20.0, "KC"), _p("te1", "TE", 10.0, "KC")]
    corr = build_correlation_matrix(players)
    assert corr[0, 1] == pytest.approx(0.45)


def test_build_correlation_matrix_wr_wr_same_team_is_negative():
    players = [_p("wr1", "WR", 15.0, "CAR"), _p("wr2", "WR", 12.0, "CAR")]
    corr = build_correlation_matrix(players)
    assert corr[0, 1] == pytest.approx(-0.225)


def test_build_correlation_matrix_different_teams_is_zero():
    players = [_p("wr1", "WR", 15.0, "CAR"), _p("wr2", "WR", 12.0, "DAL")]
    corr = build_correlation_matrix(players)
    assert corr[0, 1] == 0.0


def test_build_correlation_matrix_rb_pairs_are_zero():
    players = [_p("rb1", "RB", 15.0, "CAR"), _p("rb2", "RB", 12.0, "CAR")]
    corr = build_correlation_matrix(players)
    assert corr[0, 1] == 0.0


def test_simulate_scores_zero_projection_player_never_contributes():
    players = [_p("rb1", "RB", 10.0), _p("bye_wk", "WR", 0.0)]
    scores = simulate_scores(players, trials=500, rng=_rng())
    assert (scores[:, 1] == 0.0).all()
    assert (scores[:, 0] > 0).all()


def test_simulate_matchup_heavy_favorite_wins_most_trials():
    team_a = [_p("qb_a", "QB", 40.0, "AAA")]
    team_b = [_p("qb_b", "QB", 5.0, "BBB")]
    result = simulate_matchup(team_a, team_b, trials=5000, rng=_rng())
    assert result["win_prob_a"] > 0.95
    assert result["win_prob_a"] + result["win_prob_b"] == pytest.approx(1.0, abs=1e-6)
    assert result["score_a"]["mean"] > result["score_b"]["mean"]


def test_simulate_matchup_evenly_matched_is_close_to_50_50():
    team_a = [_p("qb_a", "QB", 20.0, "AAA")]
    team_b = [_p("qb_b", "QB", 20.0, "BBB")]
    result = simulate_matchup(team_a, team_b, trials=5000, rng=_rng())
    assert 0.4 < result["win_prob_a"] < 0.6


def test_simulate_season_undefeated_favorite_has_high_playoff_odds():
    standings_now = {
        1: {"wins": 8, "losses": 0, "fpts": 1000.0},
        2: {"wins": 0, "losses": 8, "fpts": 500.0},
        3: {"wins": 4, "losses": 4, "fpts": 750.0},
        4: {"wins": 4, "losses": 4, "fpts": 750.0},
    }
    remaining_weeks = {9: [(1, 2), (3, 4)]}
    weekly_starters = {
        9: {
            1: [_p("a", "QB", 30.0, "AAA")],
            2: [_p("b", "QB", 10.0, "BBB")],
            3: [_p("c", "QB", 20.0, "CCC")],
            4: [_p("d", "QB", 20.0, "DDD")],
        }
    }
    odds = simulate_season(
        standings_now, remaining_weeks, weekly_starters, slot_requirements={"QB": 1},
        playoff_teams=2, trials=2000, rng=_rng(),
    )
    assert odds[1] > 0.95  # 8-0 heading into one more likely win, clears top 2 easily
    assert odds[2] < 0.2  # 0-8 with a tough final matchup


def test_simulate_season_returns_odds_for_every_roster():
    standings_now = {1: {"wins": 0, "losses": 0, "fpts": 0.0}, 2: {"wins": 0, "losses": 0, "fpts": 0.0}}
    odds = simulate_season(
        standings_now, remaining_weeks={}, weekly_starters={}, slot_requirements={},
        playoff_teams=1, trials=100, rng=_rng(),
    )
    assert set(odds.keys()) == {1, 2}
    # No remaining games and tied standings -- lexsort is deterministic, so
    # exactly one of the two takes 100% of trials and the other 0%, but
    # together they must account for every trial.
    assert odds[1] + odds[2] == pytest.approx(1.0)
