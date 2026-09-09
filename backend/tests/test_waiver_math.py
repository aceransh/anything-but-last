from app.waiver_math import (
    SEASON_LENGTH_WEEKS,
    compute_competitor_multiplier,
    compute_faab_bid,
    compute_position_scarcity,
    compute_roi_temporal,
    rank_waiver_targets,
)


def test_roi_temporal_full_season_at_week_one():
    assert compute_roi_temporal(1) == SEASON_LENGTH_WEEKS / SEASON_LENGTH_WEEKS


def test_roi_temporal_decays_toward_end_of_season():
    assert compute_roi_temporal(18) == 1 / SEASON_LENGTH_WEEKS
    assert compute_roi_temporal(10) > compute_roi_temporal(17)


def test_roi_temporal_clamped_for_out_of_range_week():
    assert compute_roi_temporal(19) == 0.0


def test_position_scarcity_scales_with_supply_and_demand():
    slot_requirements = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}
    # 12 teams x 1 K slot = 12 slots chasing only 2 free-agent kickers -> scarce.
    scarce = compute_position_scarcity("K", slot_requirements, num_teams=12, free_agent_counts_by_position={"K": 2})
    # Same demand, but a deep free-agent pool -> much less scarce.
    plentiful = compute_position_scarcity(
        "K", slot_requirements, num_teams=12, free_agent_counts_by_position={"K": 40}
    )
    assert scarce > plentiful


def test_position_scarcity_clamped_when_no_free_agents_at_all():
    slot_requirements = {"QB": 1}
    result = compute_position_scarcity("QB", slot_requirements, num_teams=12, free_agent_counts_by_position={})
    assert result == 2.5  # SCARCITY_MAX


def test_position_scarcity_neutral_for_position_with_no_starting_slot():
    result = compute_position_scarcity(
        "DEF", slot_requirements={"QB": 1}, num_teams=12, free_agent_counts_by_position={"DEF": 5}
    )
    assert result == 1.0


def test_competitor_multiplier_no_rivals_is_baseline():
    assert compute_competitor_multiplier([], league_median_faab_remaining=50) == 1.0


def test_competitor_multiplier_scales_with_real_competition():
    # No rival gets any value from this player, or none can afford to bid.
    none_competing = compute_competitor_multiplier(
        [(0.0, 80.0), (-1.0, 90.0)], league_median_faab_remaining=50
    )
    assert none_competing == 1.0

    # Every rival would benefit and has above-median budget.
    all_competing = compute_competitor_multiplier(
        [(5.0, 80.0), (3.0, 90.0)], league_median_faab_remaining=50
    )
    assert all_competing == 2.0

    # A rival with real need but no money left doesn't count as competition.
    broke_rival = compute_competitor_multiplier([(5.0, 0.0)], league_median_faab_remaining=50)
    assert broke_rival == 1.0


def test_faab_bid_zero_when_no_marginal_value():
    bid = compute_faab_bid(
        delta_v=0.0,
        avg_starter_value=15.0,
        roi_temporal=1.0,
        scarcity=1.0,
        faab_total=100,
        faab_remaining=100,
        competitor_multiplier=1.0,
    )
    assert bid == 0


def test_faab_bid_zero_when_no_starters_to_compare_against():
    bid = compute_faab_bid(
        delta_v=5.0,
        avg_starter_value=0.0,
        roi_temporal=1.0,
        scarcity=1.0,
        faab_total=100,
        faab_remaining=100,
        competitor_multiplier=1.0,
    )
    assert bid == 0


def test_faab_bid_bounded_by_remaining_budget():
    # An enormous phi_p (huge delta_v, high scarcity, full competition) would
    # blow past the total budget without the min() bound.
    bid = compute_faab_bid(
        delta_v=50.0,
        avg_starter_value=1.0,
        roi_temporal=1.0,
        scarcity=2.5,
        faab_total=100,
        faab_remaining=12,
        competitor_multiplier=2.0,
        )
    assert bid == 12


def test_faab_bid_never_negative():
    bid = compute_faab_bid(
        delta_v=-5.0,
        avg_starter_value=15.0,
        roi_temporal=1.0,
        scarcity=1.0,
        faab_total=100,
        faab_remaining=100,
        competitor_multiplier=1.0,
    )
    assert bid == 0


def _player(player_id, position, projected_points, team=None):
    return {
        "player_id": player_id,
        "position": position,
        "projected_points": projected_points,
        "name": player_id,
        "team": team,
        "injury_status": None,
    }


def test_rank_waiver_targets_orders_by_recommended_bid():
    slot_requirements = {"QB": 1, "RB": 1, "WR": 1}
    user_roster = [
        _player("qb1", "QB", 20),
        _player("rb1", "RB", 10),
        _player("wr1", "WR", 8),
    ]
    # A big RB upgrade should outrank a marginal WR upgrade.
    candidates = [
        _player("rb_fa", "RB", 25),
        _player("wr_fa", "WR", 9),
    ]
    rival_rosters = {
        2: {"players": [_player("rb2", "RB", 5)], "faab_remaining": 50},
        3: {"players": [_player("wr2", "WR", 5)], "faab_remaining": 50},
    }

    ranked = rank_waiver_targets(
        candidates,
        user_roster,
        rival_rosters,
        slot_requirements,
        week=3,
        faab_total=100,
        faab_remaining=100,
        num_teams=10,
        free_agent_counts_by_position={"RB": 8, "WR": 8},
    )

    assert [c["player_id"] for c in ranked] == ["rb_fa", "wr_fa"]
    assert ranked[0]["delta_v"] > ranked[1]["delta_v"]
    assert ranked[0]["recommended_bid"] >= ranked[1]["recommended_bid"]
