from app.trade_finder import (
    best_package,
    build_trade_graph,
    cycle_to_moves,
    find_cycles_through,
    player_marginal_value,
    rank_by_edge_value,
)


def _p(player_id, position, projected_points):
    return {"player_id": player_id, "position": position, "projected_points": projected_points}


def test_player_marginal_value_positive_when_starter_upgrades():
    pool = [_p("rb1", "RB", 10.0)]
    assert player_marginal_value(pool, {"RB": 1}, [_p("rb2", "RB", 20.0)]) == 10.0


def test_player_marginal_value_zero_when_addition_cant_crack_lineup():
    pool = [_p("rb1", "RB", 10.0)]
    assert player_marginal_value(pool, {"RB": 1}, [_p("rb2", "RB", 5.0)]) == 0.0


def test_best_package_prefers_pair_when_two_open_slots():
    # Empty roster with 2 open RB slots -- a pair fills both, so pair
    # value is the sum of both singles, beating any one player alone.
    giver_pool = [_p("rb1", "RB", 10.0), _p("rb2", "RB", 8.0), _p("rb3", "RB", 1.0)]
    package = best_package(giver_pool, receiver_pool=[], slot_requirements={"RB": 2})
    assert package == {"player_ids": ["rb1", "rb2"], "marginal_value": 18.0}


def test_best_package_pair_is_not_naive_sum_when_slots_compete():
    # Only one open FLEX slot -- two flex-eligible additions compete for
    # it, so the pair's real marginal value is the better single, not the
    # sum of both (proves this calls optimize_lineup on the real pool,
    # not just adding up independent single-player marginal values).
    receiver_pool = [_p("qb1", "QB", 20.0)]
    giver_pool = [_p("rb1", "RB", 5.0), _p("wr1", "WR", 4.0)]
    slot_requirements = {"QB": 1, "FLEX": 1}

    package = best_package(giver_pool, receiver_pool, slot_requirements)

    assert package == {"player_ids": ["rb1"], "marginal_value": 5.0}


def test_best_package_returns_none_when_nothing_helps():
    receiver_pool = [_p("rb1", "RB", 50.0)]
    giver_pool = [_p("rb2", "RB", 1.0)]
    assert best_package(giver_pool, receiver_pool, slot_requirements={"RB": 1}) is None


def test_build_trade_graph_only_includes_positive_edges():
    rosters = {
        1: [_p("rb_strong", "RB", 50.0)],
        2: [_p("rb_weak", "RB", 1.0)],
    }
    slot_requirements = {"RB": 1}

    edges = build_trade_graph(rosters, slot_requirements)

    # 1 -> 2 helps (2's weak RB gets upgraded); 2 -> 1 doesn't (1's RB is
    # already better than anything 2 has to offer).
    assert (1, 2) in edges
    assert (2, 1) not in edges
    assert edges[(1, 2)]["player_ids"] == ["rb_strong"]


def _cycle_edges(*pairs):
    """pairs: (from_id, to_id, player_id, value) -- single-player edges,
    enough to exercise cycle search without needing real rosters."""
    return {(f, t): {"player_ids": [pid], "marginal_value": v} for f, t, pid, v in pairs}


def test_find_cycles_through_finds_two_team_cycle():
    edges = _cycle_edges((1, 2, "a", 10.0), (2, 1, "b", 5.0))
    assert find_cycles_through(1, edges, max_length=4) == [[1, 2]]


def test_find_cycles_through_finds_three_team_cycle():
    edges = _cycle_edges((1, 2, "a", 10.0), (2, 3, "b", 5.0), (3, 1, "c", 3.0))
    assert find_cycles_through(1, edges, max_length=4) == [[1, 2, 3]]


def test_find_cycles_through_ignores_cycles_not_through_root():
    # A real 2->3->2 cycle exists, but the root (1) isn't part of it.
    edges = _cycle_edges((2, 3, "a", 10.0), (3, 2, "b", 5.0))
    assert find_cycles_through(1, edges, max_length=4) == []


def test_find_cycles_through_respects_max_length():
    # A real 4-team cycle through the root, but max_length=3 should
    # exclude it.
    edges = _cycle_edges(
        (1, 2, "a", 10.0), (2, 3, "b", 5.0), (3, 4, "c", 3.0), (4, 1, "d", 2.0)
    )
    assert find_cycles_through(1, edges, max_length=3) == []
    assert find_cycles_through(1, edges, max_length=4) == [[1, 2, 3, 4]]


def test_cycle_to_moves_expands_multi_player_edges():
    edges = {
        (1, 2): {"player_ids": ["a1"], "marginal_value": 10.0},
        (2, 1): {"player_ids": ["b1", "b2"], "marginal_value": 15.0},
    }
    moves = cycle_to_moves([1, 2], edges)
    assert moves == [
        {"player_id": "a1", "from_roster_id": 1, "to_roster_id": 2},
        {"player_id": "b1", "from_roster_id": 2, "to_roster_id": 1},
        {"player_id": "b2", "from_roster_id": 2, "to_roster_id": 1},
    ]


def test_rank_by_edge_value_sorts_by_total_cycle_value_descending():
    edges = _cycle_edges(
        (1, 2, "a", 5.0), (2, 1, "b", 1.0),  # cycle A total = 6
    ) | _cycle_edges(
        (1, 3, "c", 20.0), (3, 1, "d", 20.0),  # cycle B total = 40
    )
    ranked = rank_by_edge_value([[1, 2], [1, 3]], edges)
    assert ranked == [[1, 3], [1, 2]]
