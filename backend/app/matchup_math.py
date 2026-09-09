"""Pure, DB/network-free Monte Carlo matchup simulation and season-long
playoff-odds projection. Every player's weekly score is modeled as
Lognormal(mu_i, sigma_i^2) -- bounded below by zero and right-skewed,
unlike a Gaussian, which better fits real TD-driven fantasy scoring --
with same-real-NFL-team correlation for QB+pass-catcher stacks (positive)
and WR-WR target competition (negative). See the research PDF's
"Monte Carlo Matchup Simulator and Season-Long Playoff Odds Tracker"
section for the model this follows.

Variance has no real per-player source (same gap the draft engine
documented for RotoBaller/FantasyPros/Sleeper -- see src/CLAUDE.md's
`_synthetic_std_dev`): WEEKLY_VOLATILITY_PCT/WR_VOLATILITY_DISCOUNT/
MIN_VOLATILITY_PCT below mirror that same reviewed proxy, minus its
ADP-gated Dead Zone/backup-RB premiums, which don't apply to a weekly,
ADP-free context. These constants are deliberately duplicated rather than
imported from `src/` -- this app shares nothing at runtime with the draft
copilot by design (see CLAUDE.md's "Season Tools App" section).
"""

import numpy as np

from .lineup_math import optimize_lineup

WEEKLY_VOLATILITY_PCT = 0.12
WR_VOLATILITY_DISCOUNT = 0.03
MIN_VOLATILITY_PCT = 0.02

# Same constant already documented in this app's Hybrid-engine writeup
# (the PDF's more precise 85th-percentile z-score) -- duplicated here, not
# imported, same as every other constant in this module.
CEILING_Z = 1.03643

# Midpoints of the PDF's stated ranges (+0.35 to +0.55 for QB-pass-catcher
# stacks, -0.15 to -0.30 for WR-WR target competition) -- a single point
# estimate rather than a further-tunable range, since nothing here
# calibrates it against real outcomes yet.
QB_STACK_CORRELATION = 0.45
WR_COMPETITION_CORRELATION = -0.225

SINGLE_WEEK_TRIALS = 10_000
# Season-long compounds this cost across every remaining week's matchups,
# so it deliberately uses fewer trials -- 1,000 already gives odds precise
# to roughly +/-3 percentage points, plenty for a directional number.
SEASON_TRIALS = 1_000


def weekly_std_dev(position: str, projected_points: float) -> float:
    """Synthetic proxy, used when a player carries no real floor/ceiling
    (see player_std_dev). A player projected at 0 (or less) gets 0 -- a
    fixed zero score, not a distribution, since ln(0) is undefined and
    there's nothing to model a spread around (byes, truly unprojected
    players)."""
    if projected_points <= 0:
        return 0.0
    pct = WEEKLY_VOLATILITY_PCT
    if position == "WR":
        pct = max(MIN_VOLATILITY_PCT, pct - WR_VOLATILITY_DISCOUNT)
    return projected_points * pct


def player_std_dev(player: dict) -> float:
    """Real floor/ceiling (e.g. from DraftSharks' weekly rankings, see
    draftsharks.py) replaces the synthetic proxy outright when present --
    same "real data wins, not layered on top" precedent the draft engine
    already set for its own DraftSharks variant (draft_math_ds.py).

    Deliberately the FULL floor-ceiling spread, not the draft engine's
    downside-only formula: that one feeds a risk *penalty* in RARC, where
    penalizing upside is backwards. This variance term feeds an actual
    outcome *simulation* -- the point is to reproduce the real spread of
    what could happen, both tails, so the full range is the correct
    signal here.
    """
    floor = player.get("floor_points")
    ceiling = player.get("ceiling_points")
    if floor is not None and ceiling is not None:
        return (ceiling - floor) / (2 * CEILING_Z)
    return weekly_std_dev(player["position"], player["projected_points"])


def build_lognormal_params(players: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Per-player (mu, sigma) in log-space. sigma_i^2 = ln(1 +
    (std_dev/E[Y_i])^2) -- Var(Y_i)/E[Y_i]^2 in the PDF's own formula.
    Players with 0 projected_points get mu=sigma=0 (handled as a fixed
    zero, not sampled -- see simulate_scores)."""
    mu = np.zeros(len(players))
    sigma = np.zeros(len(players))
    for i, p in enumerate(players):
        e_y = p["projected_points"]
        if e_y <= 0:
            continue
        pct = player_std_dev(p) / e_y
        sigma_sq = np.log(1 + pct**2)
        sigma[i] = np.sqrt(sigma_sq)
        mu[i] = np.log(e_y) - sigma_sq / 2
    return mu, sigma


def build_correlation_matrix(players: list[dict]) -> np.ndarray:
    """1 on the diagonal; QB_STACK_CORRELATION for same-real-NFL-team QB +
    (WR or TE) pairs; WR_COMPETITION_CORRELATION for same-real-NFL-team
    WR-WR pairs (matching the PDF's WR-WR-specific formula, not
    lineup_math.py's broader WR/TE stack-flagging scope, which serves a
    different purpose); 0 otherwise. Computed across the full player pool
    regardless of fantasy side -- real-world stat correlation depends on
    the actual NFL game, not who owns the players in fantasy.
    """
    n = len(players)
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = players[i], players[j]
            if not a.get("team") or a["team"] != b.get("team"):
                continue
            positions = {a["position"], b["position"]}
            if positions == {"QB", "WR"} or positions == {"QB", "TE"}:
                rho = QB_STACK_CORRELATION
            elif positions == {"WR"}:
                rho = WR_COMPETITION_CORRELATION
            else:
                continue
            corr[i, j] = corr[j, i] = rho
    return corr


def simulate_scores(players: list[dict], trials: int, rng: np.random.Generator) -> np.ndarray:
    """Correlated Monte Carlo draws, shape (trials, len(players)). A
    multivariate lognormal is exactly exp(multivariate normal), so this
    draws correlated normals in log-space (using each player's own sigma
    as the covariance scale) and exponentiates. Zero-projection players
    are excluded from the multivariate draw (a zero-variance entry would
    make the covariance matrix singular) and reinserted as a zero column.
    """
    live_idx = [i for i, p in enumerate(players) if p["projected_points"] > 0]
    result = np.zeros((trials, len(players)))
    if not live_idx:
        return result

    live_players = [players[i] for i in live_idx]
    mu, sigma = build_lognormal_params(live_players)
    corr = build_correlation_matrix(live_players)
    cov = corr * np.outer(sigma, sigma)

    # method="eigh" tolerates a not-strictly-PSD matrix via eigenvalue
    # clipping -- a safety net since these correlations are a heuristic
    # structure, not a measured one.
    draws = rng.multivariate_normal(mu, cov, size=trials, method="eigh")
    result[:, live_idx] = np.exp(draws)
    return result


def simulate_matchup(
    starters_a: list[dict],
    starters_b: list[dict],
    trials: int = SINGLE_WEEK_TRIALS,
    rng: np.random.Generator | None = None,
) -> dict:
    """Takes each team's actual starting lineup as already resolved by the
    caller -- for the real single-week matchup this is a manager's real,
    already-set Sleeper lineup (lineup_math.resolve_real_starters), not a
    recomputed optimum, since a matchup is about who's actually playing,
    not who theoretically should be (see routers/matchup.py). Simulates
    the combined pool once so cross-team same-real-NFL-team correlation is
    captured correctly, splitting back into each side's per-trial total.

    Unlike this function, simulate_season below still calls optimize_lineup
    per remaining week -- a deliberate difference, not an inconsistency:
    future unplayed weeks have no real "already-set" lineup to use yet.
    """
    rng = rng or np.random.default_rng()
    pool = starters_a + starters_b
    scores = simulate_scores(pool, trials, rng)
    scores_a = scores[:, : len(starters_a)].sum(axis=1)
    scores_b = scores[:, len(starters_a) :].sum(axis=1)

    def _stats(scores: np.ndarray) -> dict:
        return {
            "mean": float(scores.mean()),
            "median": float(np.median(scores)),
            "p10": float(np.percentile(scores, 10)),
            "p90": float(np.percentile(scores, 90)),
        }

    return {
        "win_prob_a": float(np.mean(scores_a > scores_b)),
        "win_prob_b": float(np.mean(scores_b > scores_a)),
        "score_a": _stats(scores_a),
        "score_b": _stats(scores_b),
        "starters_a": starters_a,
        "starters_b": starters_b,
    }


def simulate_season(
    standings_now: dict[int, dict],
    remaining_weeks: dict[int, list[tuple[int, int]]],
    weekly_starters: dict[int, dict[int, list[dict]]],
    slot_requirements: dict[str, int],
    playoff_teams: int,
    trials: int = SEASON_TRIALS,
    rng: np.random.Generator | None = None,
) -> dict[int, float]:
    """standings_now: {roster_id: {"wins": int, "losses": int, "fpts":
    float}} -- current real standings, the trial baseline every roster
    starts from. remaining_weeks: {week: [(roster_id_a, roster_id_b),
    ...]} -- the real remaining schedule. weekly_starters: {week:
    {roster_id: [player, ...]}} -- each roster's full player pool for
    that week (optimize_lineup is run here, per matchup, same as
    simulate_matchup -- a matchup is about who's actually starting).

    No cross-week correlation is modeled (each week's score is drawn
    independently) and no real Sleeper tiebreaker rule is applied --
    standings are ranked by (wins, fpts) descending, and a continuous
    Monte Carlo score tie has ~zero probability, so this needs no real
    tie-break logic (see CLAUDE.md's "Multi-Team Trade Finder"/"Trade
    Evaluator" write-ups for the same category of documented Sleeper-data
    simplification elsewhere in this app).

    Returns {roster_id: playoff_odds} -- the fraction of trials in which
    that roster finishes inside the top playoff_teams spots.
    """
    rng = rng or np.random.default_rng()
    roster_ids = list(standings_now.keys())
    wins = {rid: np.full(trials, float(standings_now[rid]["wins"])) for rid in roster_ids}
    fpts = {rid: np.full(trials, float(standings_now[rid]["fpts"])) for rid in roster_ids}

    for week, matchups in remaining_weeks.items():
        starters_by_roster = weekly_starters.get(week, {})
        for roster_a, roster_b in matchups:
            pool_a = starters_by_roster.get(roster_a, [])
            pool_b = starters_by_roster.get(roster_b, [])
            if not pool_a and not pool_b:
                continue
            starters_a = optimize_lineup(pool_a, slot_requirements)["starters"]
            starters_b = optimize_lineup(pool_b, slot_requirements)["starters"]

            scores = simulate_scores(starters_a + starters_b, trials, rng)
            score_a = scores[:, : len(starters_a)].sum(axis=1)
            score_b = scores[:, len(starters_a) :].sum(axis=1)

            wins[roster_a] += score_a > score_b
            wins[roster_b] += score_b > score_a
            fpts[roster_a] += score_a
            fpts[roster_b] += score_b

    # Rank each of the `trials` parallel seasons independently: stack
    # (wins, fpts) per roster into one (trials, roster) matrix per stat,
    # then argsort each trial's column to get that trial's standings.
    wins_matrix = np.stack([wins[rid] for rid in roster_ids], axis=1)
    fpts_matrix = np.stack([fpts[rid] for rid in roster_ids], axis=1)

    # lexsort ranks by the last key first -- fpts as the primary tiebreak
    # after wins, both descending, per trial (row).
    playoff_counts = {rid: 0 for rid in roster_ids}
    for t in range(trials):
        order = np.lexsort((-fpts_matrix[t], -wins_matrix[t]))
        for rank, roster_idx in enumerate(order):
            if rank < playoff_teams:
                playoff_counts[roster_ids[roster_idx]] += 1

    return {rid: playoff_counts[rid] / trials for rid in roster_ids}
