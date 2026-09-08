"""Pure, DB/network-free trade evaluation math -- reuses the greedy
lineup optimizer from lineup_math.py rather than duplicating it, so a
trade's lineup impact is computed with the exact same algorithm that
decides a real week's starters. Supports any number of participating
teams (2+), not just a pairwise trade.

The verdict is driven by real week-by-week optimal-lineup impact, not
raw summed points of the traded players -- see build_verdict and
_sum_weekly_lineup_impact below for why that distinction matters (the
"2-for-1 trap": a team can receive more total points than it gives up
and still be worse off, because it can only start so many players).
"""

from .lineup_math import optimize_lineup


def build_verdict(differential: float, threshold: float) -> str:
    if abs(differential) < threshold:
        return "Roughly even trade"
    if differential > 0:
        return f"Gains {differential:.1f} pts over the rest of the season"
    return f"Loses {abs(differential):.1f} pts over the rest of the season"


def _sum_weekly_lineup_impact(
    weekly_pools: dict[int, list[dict]],
    slot_requirements: dict[str, int],
    outgoing_ids: set[str],
    incoming_ids: set[str],
    weekly_player_lookup: dict[int, dict[str, dict]],
) -> dict:
    """Sums each remaining week's own optimal-lineup delta, rather than
    optimizing once against season-total points. This is the difference
    that actually matters: a player's rest-of-season total can tie
    another's while one is a bye-week-complementary asset and the other
    is a steady, redundant one -- collapsing to one number before
    optimizing can't tell those apart, but re-optimizing per week can.
    """
    before_total = 0.0
    after_total = 0.0
    for week, pool in weekly_pools.items():
        before_total += optimize_lineup(pool, slot_requirements)["total_projected_points"]

        lookup = weekly_player_lookup.get(week, {})
        incoming_this_week = [lookup[pid] for pid in incoming_ids if pid in lookup]
        post_pool = [p for p in pool if p["player_id"] not in outgoing_ids] + incoming_this_week
        after_total += optimize_lineup(post_pool, slot_requirements)["total_projected_points"]

    return {
        "before_total_projected_points": before_total,
        "after_total_projected_points": after_total,
        "change": after_total - before_total,
    }


def evaluate_trade(
    rosters: dict[int, list[dict]],
    weekly_rosters: dict[int, dict[int, list[dict]]],
    moves: list[dict],
    slot_requirements: dict[str, int],
    threshold: float = 5.0,
) -> dict:
    """rosters: {roster_id: [player, ...]} -- every participating team's
    full current roster, valued by rest-of-season point totals (used for
    the giving/receiving display totals and player lists, and to
    validate that moves reference real rostered players).

    weekly_rosters: {week: {roster_id: [player, ...]}} -- the same
    rosters, but re-fetched per remaining week with that week's own
    point value per player (a player missing from a given week, e.g. a
    bye, is simply absent from that week's list). This is what actually
    drives the verdict -- see _sum_weekly_lineup_impact.

    moves: [{"player_id", "from_roster_id", "to_roster_id"}, ...] -- one
    entry per player changing hands. A 2-team trade is just the N=2 case
    of this same shape.

    Raises ValueError if a move's player isn't actually on its
    from_roster, or references a roster not in `rosters`.
    """
    player_lookup = {
        roster_id: {p["player_id"]: p for p in players} for roster_id, players in rosters.items()
    }

    for move in moves:
        from_roster = player_lookup.get(move["from_roster_id"])
        if from_roster is None or move["to_roster_id"] not in rosters:
            raise ValueError(f"Trade references a roster not in this trade: {move}")
        if move["player_id"] not in from_roster:
            raise ValueError(f"{move['player_id']} is not on roster {move['from_roster_id']}")

    # A player's own per-week value doesn't change hands with a trade --
    # this just lets us look up "what would this incoming player have
    # scored in week w" regardless of which roster they came from.
    weekly_player_lookup: dict[int, dict[str, dict]] = {
        week: {p["player_id"]: p for pool in week_rosters.values() for p in pool}
        for week, week_rosters in weekly_rosters.items()
    }

    teams = []
    for roster_id, pool in rosters.items():
        outgoing_ids = {m["player_id"] for m in moves if m["from_roster_id"] == roster_id}
        incoming_players = [
            player_lookup[m["from_roster_id"]][m["player_id"]]
            for m in moves
            if m["to_roster_id"] == roster_id
        ]
        incoming_ids = {p["player_id"] for p in incoming_players}

        giving_players = [p for p in pool if p["player_id"] in outgoing_ids]
        giving_total = sum(p["projected_points"] for p in giving_players)
        receiving_total = sum(p["projected_points"] for p in incoming_players)

        weekly_pools = {
            week: week_rosters.get(roster_id, []) for week, week_rosters in weekly_rosters.items()
        }
        lineup_impact = _sum_weekly_lineup_impact(
            weekly_pools, slot_requirements, outgoing_ids, incoming_ids, weekly_player_lookup
        )

        teams.append(
            {
                "roster_id": roster_id,
                "giving_players": giving_players,
                "receiving_players": incoming_players,
                "giving_total": giving_total,
                "receiving_total": receiving_total,
                "differential": lineup_impact["change"],
                "verdict": build_verdict(lineup_impact["change"], threshold),
                "lineup_impact": lineup_impact,
            }
        )

    return {"teams": teams}
