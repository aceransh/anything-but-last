"""Pure, DB/network-free trade evaluation math -- reuses the greedy
lineup optimizer from lineup_math.py rather than duplicating it, so a
trade's lineup impact is computed with the exact same algorithm that
decides a real week's starters. Supports any number of participating
teams (2+), not just a pairwise trade.
"""

from .lineup_math import optimize_lineup


def build_verdict(differential: float, threshold: float) -> str:
    if abs(differential) < threshold:
        return "Roughly even trade"
    if differential > 0:
        return f"Gains {differential:.1f} pts over the rest of the season"
    return f"Loses {abs(differential):.1f} pts over the rest of the season"


def _lineup_impact(pool: list[dict], slot_requirements: dict[str, int], post_pool: list[dict]) -> dict:
    before = optimize_lineup(pool, slot_requirements)["total_projected_points"]
    after = optimize_lineup(post_pool, slot_requirements)["total_projected_points"]
    return {
        "before_total_projected_points": before,
        "after_total_projected_points": after,
        "change": after - before,
    }


def evaluate_trade(
    rosters: dict[int, list[dict]],
    moves: list[dict],
    slot_requirements: dict[str, int],
    threshold: float = 5.0,
) -> dict:
    """rosters: {roster_id: [player_dict, ...]} -- every participating
    team's full current roster (not just the traded players -- the full
    pool is needed to recompute each team's optimal lineup after the
    trade), each player as
    {player_id, position, projected_points, name, team, injury_status}.

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

    teams = []
    for roster_id, pool in rosters.items():
        outgoing_ids = {m["player_id"] for m in moves if m["from_roster_id"] == roster_id}
        incoming_players = [
            player_lookup[m["from_roster_id"]][m["player_id"]]
            for m in moves
            if m["to_roster_id"] == roster_id
        ]
        giving_players = [p for p in pool if p["player_id"] in outgoing_ids]
        giving_total = sum(p["projected_points"] for p in giving_players)
        receiving_total = sum(p["projected_points"] for p in incoming_players)
        differential = receiving_total - giving_total

        post_pool = [p for p in pool if p["player_id"] not in outgoing_ids] + incoming_players

        teams.append(
            {
                "roster_id": roster_id,
                "giving_players": giving_players,
                "receiving_players": incoming_players,
                "giving_total": giving_total,
                "receiving_total": receiving_total,
                "differential": differential,
                "verdict": build_verdict(differential, threshold),
                "lineup_impact": _lineup_impact(pool, slot_requirements, post_pool),
            }
        )

    return {"teams": teams}
