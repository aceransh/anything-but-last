"""Pure, DB/network-free FAAB bid valuation -- research PDF's
§"4. Event-Driven Waiver-Wire Engine and Algorithmic FAAB Valuation"
(page 9):

    ROI_temporal(w) = (17 - w + 1) / 17
    phi_p = (delta_V_p / V_starter_avg) * ROI_temporal(w) * gamma_scarcity(pos)
    delta_V_p = V_opt(R U {p}) - V_opt(R)
    B*_p = min(FAAB_remaining, floor(FAAB_total * phi_p * delta_competitor))

Four deliberate deviations from the literal PDF -- see CLAUDE.md's "FAAB
Waiver Bid Valuation" section for the full reasoning behind each:

1. Season length is 18, not 17, matching trade_math.py's own
   LAST_SCORED_WEEK convention for internal consistency.
2. V_starter_avg (undefined in the PDF) is the caller's own current
   lineup's points-per-starter -- grounded in data already fetched.
3. gamma_scarcity (named but not formulated in the PDF) is league-wide
   starting slots at a position divided by the real free-agent supply at
   that position this week.
4. delta_competitor (PDF: "rival FAAB balances and urgent roster needs")
   uses real, already-fetched rival marginal-value + FAAB data rather than
   the PDF's separate, unbuilt historical Opponent Behavioral Profiling
   engine -- see compute_competitor_multiplier.

Reuses trade_finder.player_marginal_value for delta_V_p and
lineup_math.optimize_lineup for V_starter_avg rather than reimplementing
either -- same-app reuse, not a duplicate optimizer.
"""

from .lineup_math import optimize_lineup
from .trade_finder import player_marginal_value

# trade_math.py's LAST_SCORED_WEEK convention, reused here for the same
# reason: internal consistency beats importing the PDF's literal 17.
SEASON_LENGTH_WEEKS = 18

# Position-scarcity multiplier is clamped to this band so a position with a
# tiny free-agent pool (K/DEF, usually near-fully-rostered) doesn't produce
# an unbounded ratio -- a single available kicker against 12 teams' worth of
# K slots is "scarce", not "1200% more valuable than everything else".
SCARCITY_MIN = 0.5
SCARCITY_MAX = 2.5

# delta_competitor only ever pushes a bid UP from its base phi_p, never
# down -- real competitive pressure should raise a bid, but its absence
# isn't a reason to bid less than the player is independently worth to you.
COMPETITOR_MULTIPLIER_MIN = 1.0
COMPETITOR_MULTIPLIER_MAX = 2.0
COMPETITOR_MULTIPLIER_STEP = 1.0  # fraction=1.0 (every rival competes) -> MIN + STEP == MAX


def compute_roi_temporal(week: int) -> float:
    """(18 - w + 1) / 18, clamped to [0, 1] -- a Week 2 pickup is worth
    close to a full season's production; a Week 17 pickup is worth almost
    none, regardless of how good the player is.
    """
    roi = (SEASON_LENGTH_WEEKS - week + 1) / SEASON_LENGTH_WEEKS
    return max(0.0, min(1.0, roi))


def compute_position_scarcity(
    position: str,
    slot_requirements: dict[str, int],
    num_teams: int,
    free_agent_counts_by_position: dict[str, int],
) -> float:
    """(league-wide starting slots at this position) / (real free agents
    at this position with a nonzero projection this week). FLEX-eligible
    positions (RB/WR/TE) don't get their own FLEX slots counted per
    position here -- this is about a position's OWN named slot demand, not
    an attempt to fractionally split FLEX across three positions.
    """
    slots_leaguewide = slot_requirements.get(position, 0) * num_teams
    if slots_leaguewide == 0:
        return 1.0
    free_agents = free_agent_counts_by_position.get(position, 0)
    if free_agents == 0:
        return SCARCITY_MAX
    ratio = slots_leaguewide / free_agents
    return max(SCARCITY_MIN, min(SCARCITY_MAX, ratio))


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def compute_competitor_multiplier(
    rival_deltas: list[tuple[float, float]], league_median_faab_remaining: float
) -> float:
    """rival_deltas is one (delta_v, faab_remaining) pair per rival roster
    -- their own marginal value from picking up this player, and their real
    remaining FAAB budget. A rival counts as real competition only if the
    player would actually help their lineup (delta_v > 0) AND they can
    afford to bid meaningfully (faab_remaining at or above the league
    median) -- a rival with zero use for the position, or with $0 left,
    isn't competitive pressure. Scales linearly from 1.0 (no real
    competition) to 2.0 (every rival is a real competitor).
    """
    if not rival_deltas:
        return COMPETITOR_MULTIPLIER_MIN
    competing = sum(
        1
        for delta_v, faab_remaining in rival_deltas
        if delta_v > 0 and faab_remaining >= league_median_faab_remaining
    )
    fraction = competing / len(rival_deltas)
    multiplier = COMPETITOR_MULTIPLIER_MIN + COMPETITOR_MULTIPLIER_STEP * fraction
    return max(COMPETITOR_MULTIPLIER_MIN, min(COMPETITOR_MULTIPLIER_MAX, multiplier))


def compute_faab_bid(
    delta_v: float,
    avg_starter_value: float,
    roi_temporal: float,
    scarcity: float,
    faab_total: int,
    faab_remaining: int,
    competitor_multiplier: float,
) -> int:
    """B*_p = min(FAAB_remaining, floor(FAAB_total * phi_p * delta_competitor)).
    avg_starter_value <= 0 means the caller's own lineup has no scored
    starters to compare against (e.g. week 18 with nothing left to play) --
    phi_p is undefined in that case, so the bid is 0 rather than dividing
    by zero.
    """
    if avg_starter_value <= 0 or delta_v <= 0:
        return 0
    phi = (delta_v / avg_starter_value) * roi_temporal * scarcity
    bid = int(faab_total * phi * competitor_multiplier)
    return max(0, min(faab_remaining, bid))


def average_starter_value(roster_players: list[dict], slot_requirements: dict[str, int]) -> float:
    lineup = optimize_lineup(roster_players, slot_requirements)
    num_starters = len(lineup["starters"])
    if num_starters == 0:
        return 0.0
    return lineup["total_projected_points"] / num_starters


def rank_waiver_targets(
    candidates: list[dict],
    user_roster_players: list[dict],
    rival_rosters: dict[int, dict],
    slot_requirements: dict[str, int],
    week: int,
    faab_total: int,
    faab_remaining: int,
    num_teams: int,
    free_agent_counts_by_position: dict[str, int],
) -> list[dict]:
    """candidates: free-agent player dicts (player_id/position/team/name/
    injury_status/projected_points) -- typically a shortlist (e.g. the top
    N by trending add count), NOT the full free-agent pool. rival_rosters:
    every OTHER roster, keyed by roster_id, as {"players": [...],
    "faab_remaining": int} -- used only to feed
    compute_competitor_multiplier's rival deltas. free_agent_counts_by_position
    MUST be tallied by the caller from the TRUE full free-agent pool (every
    unrostered projected player, not just this shortlist) -- gamma_scarcity
    is about real position-wide supply/demand, and a shortlist of ~15
    trending players is too thin a sample to estimate that from (every
    position looks "scarce" if you only ever look at 15 players total).

    Returns candidates sorted by recommended_bid (then delta_v) descending,
    each annotated with delta_v/roi_temporal/scarcity/competitor_multiplier/
    recommended_bid alongside its original fields.
    """
    roi_temporal = compute_roi_temporal(week)
    avg_starter_value = average_starter_value(user_roster_players, slot_requirements)

    rival_faab_remaining = [rival["faab_remaining"] for rival in rival_rosters.values()]
    league_median_faab = _median(rival_faab_remaining)

    ranked = []
    for candidate in candidates:
        delta_v = player_marginal_value(user_roster_players, slot_requirements, [candidate])
        scarcity = compute_position_scarcity(
            candidate["position"], slot_requirements, num_teams, free_agent_counts_by_position
        )

        rival_deltas = [
            (
                player_marginal_value(rival["players"], slot_requirements, [candidate]),
                rival["faab_remaining"],
            )
            for rival in rival_rosters.values()
        ]
        competitor_multiplier = compute_competitor_multiplier(rival_deltas, league_median_faab)

        recommended_bid = compute_faab_bid(
            delta_v, avg_starter_value, roi_temporal, scarcity, faab_total, faab_remaining, competitor_multiplier
        )

        ranked.append(
            {
                **candidate,
                "delta_v": delta_v,
                "roi_temporal": roi_temporal,
                "scarcity": scarcity,
                "competitor_multiplier": competitor_multiplier,
                "recommended_bid": recommended_bid,
            }
        )

    ranked.sort(key=lambda c: (c["recommended_bid"], c["delta_v"]), reverse=True)
    return ranked
