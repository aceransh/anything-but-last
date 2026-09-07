from app.lineup_math import build_slot_requirements, optimize_lineup

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
