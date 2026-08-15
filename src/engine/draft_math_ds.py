"""Draft valuation engine -- DraftSharks (DS) variant.

Deliberately duplicated from draft_math.py rather than modifying it in place
-- draft_math.py stays the default engine, wired to RotoBaller-derived
data/projections.csv, completely untouched by this file. This variant is
wired to data/projections_ds.csv (see src/api/update_data_draftsharks.py)
and exists for ONE reason: DraftSharks publishes real per-player floor/
ceiling projections, RotoBaller does not.

The only substantive change from draft_math.py is `_real_std_dev`, which
replaces `_synthetic_std_dev`. The original engine has no real per-player
variance data at all, so it heuristically estimates one (a flat percentage
of projected_points, with a Dead Zone RB premium, a backup-RB premium, a
high-floor discount keyed off PPG as a target-share proxy, and a WR
stability discount -- see draft_math.py's comment block for the full
rationale). All of that was a proxy for missing data. Now that real floor/
ceiling numbers exist, deriving std_dev directly from them is strictly
better than keeping the heuristic on top -- running both would double-count
the same uncertainty the heuristic was only ever guessing at, so the Dead
Zone/backup/high-floor volatility premiums are removed entirely in this
variant rather than layered on top of real data.

Two DraftSharks columns were deliberately left OUT of this variant despite
being available in the CSV, to avoid double-counting or scope creep:
- strength_of_schedule: a real projection model should already reflect a
  player's actual opponents, so this is presumed already baked into
  projected_points/consensus_projection rather than a separate signal.
- injury_risk_pct: DraftSharks defines floor as worst-case "barring
  injury," so this is NOT redundant with floor/ceiling (it's a genuinely
  separate risk dimension) -- but it's still out of scope for this specific
  floor/ceiling swap and left for a future addition if wanted.

Everything else (RARC, survival probability, portfolio impact, Pareto
frontier selection, same-team stack penalty, hard roster-construction
rules) is IDENTICAL to draft_math.py. See that file's module docstring and
inline comments for the full rationale on all of it.
"""

import functools
import math
import re

import pandas as pd

from src.engine.draft_state import compute_pick_slot
from src.engine.roster import Roster

SUFFIX_PATTERN = re.compile(r"\s+\b(jr|sr|ii|iii|iv|v)\b$")
PUNCTUATION_PATTERN = re.compile(r"[^\w\s]")

# --- Hard roster-construction rules (pool filters, not weights) -----------
# Only positions with a real structural cap live here. RB/WR have no cap --
# scarcity for those is now entirely emergent from RARC's dynamic baseline.
POSITIONAL_TARGET = {"QB": 2, "TE": 1, "K": 1, "DEF": 1}
HARD_MAX_POSITIONS = {"QB", "TE", "K", "DEF"}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}

# A 2nd TE is banned for the entire draft EXCEPT the true final round, where
# an emergency-fill 2nd TE is preferable to leaving a bench slot for a worse
# option.
TE_FINAL_ROUND_MAX = 2

KICKER_DEFENSE_ROUNDS_FROM_END = 2  # K/DEF invisible until the final 2 rounds

# Mandatory K/DEF (and any other still-open starting slot) alignment: in the
# true final round, the candidate pool is hard-restricted to whatever
# starting slots are still open -- no draft may end with an empty starting
# slot for lack of the engine ever surfacing the position.
FINAL_ROUND_REQUIRED_SLOT_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# Dynamic single-QB constraint: an elite-tier QB1 (drafted Rounds 1-6) means
# a 2nd QB is locked out for the REST of the draft -- that draft capital
# already bought a locked-in weekly starter, permanently. A late-round QB1
# (Round 9+) has no such lock; a 2nd QB there is governed by the normal
# hard-cap-at-2 filter.
QB1_ELITE_ROUND_CUTOFF = 6

ADP_FALLBACK = 999.0  # players with no meaningful ADP consensus: assume ~always available

# --- ADP standard deviation (empirical scaling, deeper picks = fuzzier ADP) ---
ADP_STD_DEV_BASE = 1.2
ADP_STD_DEV_SLOPE = 0.35
ADP_STD_DEV_SCALE_PICKS = 12.0


def calculate_adp_std_dev(adp: float) -> float:
    """sigma_ADP,i = 1.2 + 0.35 * (ADP_i / 12) -- ADP consensus gets fuzzier
    (higher variance in exactly which pick a player goes) the deeper into
    the draft it sits, since late-round ADP is thin-sample and volatile.
    """
    return ADP_STD_DEV_BASE + ADP_STD_DEV_SLOPE * (adp / ADP_STD_DEV_SCALE_PICKS)


# --- Real per-player variance (DraftSharks floor/ceiling) -------------------
# DraftSharks publishes real floor_points ("worst-case, barring injury") and
# ceiling_points ("best-case") per player -- unlike the RotoBaller-only feed
# draft_math.py is stuck estimating from nothing. DraftSharks doesn't publish
# an exact percentile definition for either bound, so CEILING_Z (already
# used elsewhere in this engine for the 85th-percentile portfolio-ceiling
# calc) is reused here as a symmetric assumption: ceiling sits CEILING_Z std
# devs above the mean and floor sits CEILING_Z std devs below it, giving
# sigma = (ceiling - floor) / (2 * CEILING_Z). This is a reasonable-
# assumption proxy, not an exact recovery of DraftSharks' internal model --
# but it's grounded in real per-player data instead of a flat heuristic.
RB_DEAD_ZONE_ADP_START = 37.0  # labeling only in this variant (see _label_candidates) -- no longer drives a variance premium, real data does
RB_DEAD_ZONE_ADP_END = 84.0

GAMES_PER_SEASON = 17

# --- RARC (Risk-Adjusted Replacement Cost) ---------------------------------
# Calibrated so a Dead Zone RB (std ~27% of projected_points) takes roughly
# a 10-15% variance discount off their raw value -- a real but proportionate
# risk penalty, not one that wipes out most of the player's value outright.
RARC_VARIANCE_LAMBDA = 0.01

# --- Reach penalty: continuous exponential decay ---------------------------
# Fires only when a player's consensus ADP sits meaningfully LATER than the
# current pick (i.e. drafting them well before the market expects them to
# go -- a genuine reach), scaled smoothly by how many (softened) ADP-std-devs
# early the reach is. The raw exp(x)-1 curve saturates its cap within ~2
# std-devs, which is far too aggressive at realistic sigma_adp scales (a
# routine 2-3 pick early call would otherwise max out identically to a
# 10-round reach) -- REACH_PENALTY_SIGMA_MULTIPLIER widens the effective
# window so only a genuinely large reach approaches the cap. Capped so an
# extreme/undefined ADP can't dominate the composite score unboundedly.
REACH_PENALTY_SIGMA_MULTIPLIER = 3.0
REACH_PENALTY_CAP = 5.0

# --- Same-team non-QB stack penalty -----------------------------------------
# Roster-conditioned, like portfolio impact: penalizes drafting a WR/TE
# candidate who'd be sharing an NFL team's finite target pool with a pass-
# catcher you already have rostered. Deliberately does NOT apply to QB
# (QB + same-team pass-catcher is a well-established POSITIVE-correlation
# strategy, not a competition risk) or to RB in either role (real-world
# analysis found RB production is driven by rushing volume/goal-line work,
# largely orthogonal to passing-game target share -- pairing an RB with a
# same-team pass-catcher is not a meaningful target-competition effect, so
# it isn't penalized here, correcting an initial intuition that it should be).
#
# WR+WR gets the largest penalty: modern NFL offenses concentrate targets
# toward a clear WR1, so two same-team WRs are close to direct, zero-sum
# competition for a shrinking pool -- and in a redraft (non-tournament)
# league there's no correlation upside to offset that risk the way there is
# for QB stacks. WR+TE is real but smaller: TE usage skews toward
# intermediate/red-zone routes vs. WR's more downfield/perimeter role, so
# the overlap is meaningful but not fully zero-sum. No source gave a precise
# same-team correlation coefficient for either pairing specifically, so
# these are a proxy calibrated to be a real, felt signal without being able
# to override a genuinely large value gap -- same design intent as
# REACH_PENALTY above, and given the same W_REACH_PENALTY-scale weight for
# comparable impact per unit.
SAME_TEAM_WR_WR_PENALTY = 1.0
SAME_TEAM_WR_TE_PENALTY = 0.4
SAME_TEAM_STACK_PENALTY_CAP = 2.0
W_SAME_TEAM_STACK_PENALTY = 15.0

# --- Portfolio impact (win probability / ceiling) --------------------------
# projected_points/std_dev in the CSV are SEASON totals, but win probability
# is inherently a per-game concept. GAMES_PER_SEASON converts to a per-game
# scale: per_game_mean = season/17, per_game_std = season_std/sqrt(17).
# Assumes iid per-game performance -- neither feed has a real per-game split
# to do better.
CEILING_Z = 1.04  # 85th percentile z-score

# --- Composite score weights (tunable; RARC dominates as the primary value
# signal, WP/ceiling nudge for roster fit, reach penalty is a strong but not
# absolute deterrent) ---
W_RARC = 1.0
W_DELTA_WP = 3.0
W_DELTA_CEILING = 1.0
W_REACH_PENALTY = 15.0

# --- Late-round high-contingency RB quota (Rounds 10+) -------------------
# Backup RBs whose own 85th-percentile ceiling (mu + CEILING_Z * std_dev)
# is at least 1.3x their own median projection -- i.e. real injury-
# replacement/committee-role upside, not just noise -- are guaranteed at
# least HIGH_CONTINGENCY_MIN_SLOTS of the 8 stream slots once WR mean
# projections start dominating late-round RARC and would otherwise crowd
# every backup RB out of the payload entirely. This is a selection-stage
# quota (like the Round 14 DEF guarantee below), not a score multiplier --
# it doesn't touch anyone's composite_score.
#
# mu + CEILING_Z*std >= 1.3*mu  <=>  std/mu >= (1.3 - 1) / CEILING_Z, solved
# algebraically from the existing ceiling formula rather than a new
# hardcoded ratio.
HIGH_CONTINGENCY_ROUND_START = 10
HIGH_CONTINGENCY_CEILING_MULTIPLIER = 1.3
HIGH_CONTINGENCY_STD_RATIO = (HIGH_CONTINGENCY_CEILING_MULTIPLIER - 1.0) / CEILING_Z
HIGH_CONTINGENCY_MIN_SLOTS = 2

# --- Pareto candidate stream sizing ---
PARETO_STREAM_MIN = 6
PARETO_STREAM_MAX = 8
PARETO_POOL_CAP = 50  # perf cap before frontier extraction
POSITION_DIVERSITY_CAP = 3  # max candidates per position in the final stream

# Opponent positional-demand conditioning: a team that still needs a
# position is meaningfully more likely to take it than raw ADP alone would
# suggest; a team whose starters are already full is less likely to reach
# for it. These are deliberately mild multipliers (not hard 0/1 gates) since
# bench-building behavior is real too.
DEMAND_MATCH_BOOST = 1.6
DEMAND_MISS_DAMPEN = 0.55
SURVIVAL_EARLY_EXIT_THRESHOLD = 0.01  # baseline order-statistic tail cutoff


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation (periods, apostrophes, hyphens, ...) and
    suffixes (Jr/Sr/II/III/IV/V), and collapse whitespace.

    Applied identically to Sleeper pick metadata and projections_ds.csv names
    so the two sides always compare as pure name-identity, regardless of
    minor punctuation formatting differences between the two sources.
    """
    normalized = name.strip().lower()
    normalized = PUNCTUATION_PATTERN.sub("", normalized)
    normalized = SUFFIX_PATTERN.sub("", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def get_drafted_names(picks: list) -> set:
    """Normalized (name, position) pairs for every drafted player, from
    Sleeper pick metadata.

    Intentionally keys off name identity only (first_name + last_name from
    `pick["metadata"]`) and never reads a team/roster field. A player's team
    in `metadata` reflects their team at pick time and can be stale or drift
    from the local projections CSV (trades, free agency); comparing on team
    would wrongly let a drafted player slip back into the available pool.

    Position is carried alongside the name (not used for the primary match)
    so callers can safely fall back to last-name+position matching --
    Sleeper's own player DB sometimes uses a nickname as first_name (e.g.
    "Kenny Gainwell") where a projections source uses the formal name
    ("Kenneth Gainwell"), which a strict full-name match misses entirely.
    See _drafted_mask().
    """
    drafted = set()
    for pick in picks:
        metadata = pick.get("metadata")
        if not metadata:
            continue
        full_name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
        if full_name:
            position = (metadata.get("position") or "").strip().upper()
            drafted.add((normalize_name(full_name), position))
    return drafted


def _last_token(normalized_name: str) -> str:
    parts = normalized_name.split(" ")
    return parts[-1] if parts else normalized_name


def _drafted_mask(df: pd.DataFrame, drafted_player_names) -> pd.Series:
    """True for rows that should be treated as drafted.

    Accepts either plain name strings (exact normalized-full-name match
    only, for backward compatibility) or (name, position) pairs as produced
    by `get_drafted_names()`. For the latter, also falls back to matching on
    (last name, position) -- but ONLY when that combination is unique across
    the entire projections pool, so two different players who happen to
    share a last name at the same position can never be confused for one
    another. This is what catches nickname/formal-name mismatches (e.g.
    Sleeper's "Kenny Gainwell" vs. a projections source's "Kenneth
    Gainwell") without needing a hardcoded nickname table.
    """
    drafted_full_names = set()
    drafted_last_pos = set()
    for entry in drafted_player_names:
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            name, position = entry
            name = normalize_name(name)
            drafted_full_names.add(name)
            if position:
                drafted_last_pos.add((_last_token(name), position))
        else:
            drafted_full_names.add(normalize_name(entry))

    names = df["player_name"].apply(normalize_name)
    positions = df["position"].astype(str).str.strip().str.upper()

    exact_match = names.isin(drafted_full_names)

    if not drafted_last_pos:
        return exact_match

    last_names = names.apply(_last_token)
    last_pos_pairs = list(zip(last_names, positions))
    unique_last_pos = pd.Series(last_pos_pairs).value_counts()
    fallback_match = pd.Series(
        [
            pair in drafted_last_pos and unique_last_pos.get(pair, 0) == 1
            for pair in last_pos_pairs
        ],
        index=df.index,
    )
    return exact_match | fallback_match


def load_projections(csv_path: str = "data/projections_ds.csv") -> pd.DataFrame:
    """Loads the DraftSharks-derived projections CSV. floor_points/
    ceiling_points are backfilled to projected_points (i.e. zero implied
    variance) for any row missing them -- this is an external-data ingestion
    boundary, not an internal invariant, so a graceful degrade here is
    appropriate even though the current data pull has zero missing values
    for either column.
    """
    df = pd.read_csv(csv_path)
    df["floor_points"] = df["floor_points"].fillna(df["projected_points"])
    df["ceiling_points"] = df["ceiling_points"].fillna(df["projected_points"])
    return df


def _kdef_unlocked(round_num: int, total_rounds: int) -> bool:
    return round_num > total_rounds - KICKER_DEFENSE_ROUNDS_FROM_END


def _normal_cdf(x: float, mean: float = 0.0, std: float = 1.0) -> float:
    if std <= 0:
        return 1.0 if x >= mean else 0.0
    z = (x - mean) / (std * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def _qb1_elite_locked(roster) -> bool:
    """True for the rest of the draft once QB1 was drafted in the Elite Tier
    (Rounds 1-6) -- a 2nd QB is never recommended again after that.
    """
    if roster is None:
        return False
    qb1_round = roster.position_first_round.get("QB")
    return qb1_round is not None and qb1_round <= QB1_ELITE_ROUND_CUTOFF


def _filter_hard_capped_positions(
    df: pd.DataFrame, roster, round_num: int = 1, total_rounds: int = 15
) -> pd.DataFrame:
    """Absolute row-filter: once a hard-max position (QB/TE/K/DEF) reaches
    its cap, it is removed from the candidate pool outright. Also drops QB
    outright once the elite-QB1 lock is active (permanent for the rest of
    the draft).

    TE's cap is 1 for the whole draft except the true final round, where it
    opens back up to 2 as a last-resort emergency fill.
    """
    if roster is None:
        return df
    position_counts = roster.position_counts
    qb_locked = position_counts.get("QB", 0) >= 1 and _qb1_elite_locked(roster)

    def effective_target(position: str) -> float:
        if position == "TE" and round_num >= total_rounds:
            return TE_FINAL_ROUND_MAX
        return POSITIONAL_TARGET.get(position, float("inf"))

    def is_over_cap(position: str) -> bool:
        if position in HARD_MAX_POSITIONS and position_counts.get(position, 0) >= effective_target(
            position
        ):
            return True
        return position == "QB" and qb_locked

    return df[~df["position"].map(is_over_cap)]


def _final_round_required_positions(roster, round_num: int, total_rounds: int) -> set | None:
    """True final round only: whatever starting slots (QB/RB/WR/TE/K/DEF,
    plus RB/WR/TE if FLEX is open) are still empty. No draft may end with an
    empty starting slot for lack of the engine ever surfacing the position.
    Returns None when there's nothing left to force.
    """
    if roster is None or round_num < total_rounds:
        return None
    open_slots = roster.open_slots()
    required = {
        position
        for position in FINAL_ROUND_REQUIRED_SLOT_POSITIONS
        if open_slots.get(position, 0) > 0
    }
    if open_slots.get("FLEX", 0) > 0:
        required |= FLEX_ELIGIBLE
    return required or None


# --- Opponent positional demand (real, from live Sleeper draft state) ------
def _team_open_starter_needs(picks: list, draft_slot: int, teams: int) -> set:
    """Builds a given team's roster from raw Sleeper picks and returns which
    starting positions (QB/RB/WR/TE, plus RB/WR/TE if FLEX is open) are
    still unfilled for them -- real opponent state, not a guess.
    """
    team_roster = Roster()
    for pick in picks:
        if pick.get("draft_slot") == draft_slot and pick.get("metadata"):
            _, pick_round, _ = compute_pick_slot(pick["pick_no"], teams)
            team_roster.add_player(
                f"{pick['metadata'].get('first_name', '')} {pick['metadata'].get('last_name', '')}".strip(),
                pick["metadata"].get("position", "BN"),
                round_num=pick_round,
            )
    open_slots = team_roster.open_slots()
    needs = {position for position in ("QB", "RB", "WR", "TE") if open_slots.get(position, 0) > 0}
    if open_slots.get("FLEX", 0) > 0:
        needs |= {"RB", "WR", "TE"}
    return needs


def compute_turn_gap_demand(
    picks: list, teams: int, total_rounds: int, current_pick_no: int, turn_gap: int
) -> list:
    """Per-step (m=1..turn_gap) the drafting team's open starter needs. This
    is what makes pick-survival probability *conditional* on real opponent
    roster state instead of treating every future pick as an independent
    draw from the global ADP distribution.
    """
    steps = []
    total_picks = teams * total_rounds
    for m in range(1, turn_gap + 1):
        pick_no = current_pick_no + m
        if pick_no > total_picks:
            steps.append(set())
            continue
        slot, _, _ = compute_pick_slot(pick_no, teams)
        steps.append(_team_open_starter_needs(picks, slot, teams))
    return steps


def _pick_probability_at_step(
    adp: float, sigma_adp: float, pick_no: int, team_needs: set, position: str
) -> float:
    """P(Draft_i,m | still available heading into pick m): the CONDITIONAL
    hazard rate -- probability of being taken at this exact pick GIVEN the
    player has survived to this point -- not the raw unconditioned ADP
    density.
    """
    already_taken_prob = _normal_cdf(pick_no - 0.5, mean=adp, std=sigma_adp)
    survived_so_far = 1.0 - already_taken_prob
    if survived_so_far < 1e-9:
        hazard = 1.0
    else:
        density_here = (
            _normal_cdf(pick_no + 0.5, mean=adp, std=sigma_adp) - already_taken_prob
        )
        hazard = density_here / survived_so_far

    if not team_needs:
        return min(1.0, hazard)
    if position in team_needs:
        return min(0.98, hazard * DEMAND_MATCH_BOOST)
    return min(1.0, hazard * DEMAND_MISS_DAMPEN)


def _survival_probability(
    adp: float, sigma_adp: float, position: str, current_pick_no: int, demand_steps: list
) -> float:
    """P(Avail_i,K) = prod_{m=1}^{N} (1 - P(Draft_i,m | Roster_m))"""
    survival = 1.0
    for m, team_needs in enumerate(demand_steps, start=1):
        p_taken = _pick_probability_at_step(adp, sigma_adp, current_pick_no + m, team_needs, position)
        survival *= 1.0 - p_taken
    return max(0.0, min(1.0, survival))


def _real_std_dev(row) -> float:
    """Real per-player variance, derived directly from DraftSharks' own
    floor_points/ceiling_points -- see the module docstring above for the
    (ceiling - floor) / (2 * CEILING_Z) derivation and its caveats. Replaces
    draft_math.py's `_synthetic_std_dev` heuristic entirely in this variant.
    """
    return max(0.0, (row["ceiling_points"] - row["floor_points"]) / (2 * CEILING_Z))


def _dynamic_baseline(position_df: pd.DataFrame) -> float:
    """B_pos(K) = expected value of the single best player at this position
    who's still available at the user's next turn:
    Σ_j P(avail_j) * mu_j * Π_{l<j}(1 - P(avail_l)), players ordered by
    descending projected value. Early-exits once the cumulative "all better
    players already gone" probability clears 99%, since the tail
    contribution beyond that is negligible.
    """
    if position_df.empty:
        return 0.0
    ordered = position_df.sort_values("effective_points", ascending=False)
    baseline = 0.0
    prob_none_better_available = 1.0
    for _, row in ordered.iterrows():
        p_avail = row["survival_prob"]
        baseline += p_avail * row["effective_points"] * prob_none_better_available
        prob_none_better_available *= 1.0 - p_avail
        if prob_none_better_available < SURVIVAL_EARLY_EXIT_THRESHOLD:
            break
    return baseline


def _apply_rarc(df: pd.DataFrame, current_pick_no: int, demand_steps: list) -> pd.DataFrame:
    """RARC_i = (mu_i - lambda * sigma_i^2) - B_pos(i)(K)"""
    df = df.copy()
    adp = df["adp"].fillna(ADP_FALLBACK)
    df["sigma_adp"] = adp.apply(calculate_adp_std_dev)
    df["std_dev"] = df.apply(_real_std_dev, axis=1)
    df["survival_prob"] = [
        _survival_probability(a, s, p, current_pick_no, demand_steps)
        for a, s, p in zip(adp, df["sigma_adp"], df["position"])
    ]

    baselines = {position: _dynamic_baseline(df[df["position"] == position]) for position in df["position"].unique()}
    df["replacement_baseline"] = df["position"].map(baselines)

    df["rarc_score"] = (
        df["effective_points"] - RARC_VARIANCE_LAMBDA * (df["std_dev"] ** 2)
    ) - df["replacement_baseline"]
    return df


def _reach_penalty(adp: float, sigma_adp: float, current_pick_no: int) -> float:
    """Continuous exponential reach penalty: fires only when the player's
    ADP sits meaningfully LATER than the current pick (drafting them well
    before the market expects -- a reach), scaled by how many (softened)
    ADP-std-devs early the reach is. See REACH_PENALTY_SIGMA_MULTIPLIER.
    """
    delta = max(0.0, (adp - current_pick_no) / (sigma_adp * REACH_PENALTY_SIGMA_MULTIPLIER))
    return min(REACH_PENALTY_CAP, math.exp(delta) - 1.0)


@functools.lru_cache(maxsize=4)
def _league_baseline_lineup(csv_path: str = "data/projections_ds.csv") -> tuple:
    """A generic 'average starting lineup' mean/std, used as the opponent
    distribution in the win-probability model. Derived directly from the
    projections pool: the Nth-best player at each starting position, where
    N = (starters needed at that position) x (12 teams), i.e. "what a
    typical team's starting lineup looks like."
    """
    df = load_projections(csv_path)
    teams = 12

    def tier_mean_std(position: str, starters_per_team: int) -> tuple:
        pool = df[df["position"] == position].sort_values("projected_points", ascending=False)
        tier = pool.iloc[: starters_per_team * teams]
        if tier.empty:
            return 0.0, 0.0
        return tier["projected_points"].mean(), tier["projected_points"].std(ddof=0)

    qb_mean, qb_std = tier_mean_std("QB", 1)
    rb_mean, rb_std = tier_mean_std("RB", 2)
    wr_mean, wr_std = tier_mean_std("WR", 2)
    te_mean, te_std = tier_mean_std("TE", 1)

    flex_pool = df[df["position"].isin(["RB", "WR", "TE"])].sort_values(
        "projected_points", ascending=False
    )
    flex_tier = flex_pool.iloc[teams * 5 : teams * 6]
    flex_mean = flex_tier["projected_points"].mean() if not flex_tier.empty else 0.0
    flex_std = flex_tier["projected_points"].std(ddof=0) if not flex_tier.empty else 0.0

    mean = qb_mean + rb_mean + wr_mean + te_mean + flex_mean
    variance = qb_std**2 + rb_std**2 + wr_std**2 + te_std**2 + flex_std**2
    return mean, math.sqrt(variance)


def _lookup_player(df: pd.DataFrame, player_name: str):
    target = normalize_name(player_name)
    matches = df[df["player_name"].apply(normalize_name) == target]
    if matches.empty:
        return None
    return matches.iloc[0]


def _build_rostered_pool(roster, projections_df: pd.DataFrame) -> list:
    """Every rostered player (starters AND bench), with their point/variance
    values -- the raw pool a greedy lineup optimizer needs. Deliberately
    ignores which literal Sleeper slot each player currently sits in.
    """
    if roster is None:
        return []
    pool = []
    seen = set()
    for slot_players in roster.slots.values():
        for player_name in slot_players:
            if player_name in seen:
                continue
            seen.add(player_name)
            row = _lookup_player(projections_df, player_name)
            if row is None:
                continue
            pool.append(
                {
                    "player_name": player_name,
                    "position": row["position"],
                    "effective_points": row["projected_points"],
                    "std_dev": _real_std_dev(row),
                }
            )
    return pool


def _optimal_lineup_value(pool: list) -> tuple:
    """Greedy top-value assignment to starting slots (1 QB, 2 RB, 2 WR, 1
    TE, then the single highest-value remaining RB/WR/TE to FLEX) --
    ALWAYS starts your best 9 regardless of which literal bench/starter
    slot a player's draft order happened to assign them to. Returns
    (mean, std) of the resulting lineup.
    """
    used = set()
    starters = []
    for position, count in (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)):
        ranked = sorted(
            (p for p in pool if p["position"] == position and p["player_name"] not in used),
            key=lambda p: -p["effective_points"],
        )
        for p in ranked[:count]:
            starters.append(p)
            used.add(p["player_name"])
    flex_ranked = sorted(
        (p for p in pool if p["position"] in FLEX_ELIGIBLE and p["player_name"] not in used),
        key=lambda p: -p["effective_points"],
    )
    if flex_ranked:
        starters.append(flex_ranked[0])
        used.add(flex_ranked[0]["player_name"])
    mean = sum(p["effective_points"] for p in starters)
    variance = sum(p["std_dev"] ** 2 for p in starters)
    return mean, math.sqrt(variance)


def _apply_portfolio_impact(df: pd.DataFrame, roster, projections_df: pd.DataFrame) -> pd.DataFrame:
    """ΔWP_i = P(Win | Roster ∪ {i}) - P(Win | Roster), ΔCeiling_i =
    Ceiling_85(Roster ∪ {i}) - Ceiling_85(Roster), both computed on a
    per-game basis (see GAMES_PER_SEASON) against a league-average lineup
    baseline (see `_league_baseline_lineup`) rather than a literal
    per-opponent weekly simulation, since no real season-schedule/opponent-
    roster data is available.

    Win probability uses ONLY the roster's own per-game std_dev as the
    spread -- `_league_baseline_lineup`'s "std" is the spread BETWEEN
    different players' season projections within a replacement tier (a
    cross-sectional quality-dispersion statistic), not a measure of how a
    single roster's own score fluctuates week to week. Treating league_mean
    as a fixed benchmark and asking "given MY roster's own game-to-game
    volatility, what's the probability I clear that benchmark" is the
    well-defined version of this question.

    "Roster ∪ {i}" is evaluated with the greedy optimizer above, run fresh
    on the full pool (current roster + candidate) for every candidate -- if
    candidate i outscores the current FLEX starter (or any starter at their
    position), the optimizer automatically bumps them into the lineup and
    pushes the displaced starter to the bench, so i gets full starter
    credit. A player who wouldn't crack the optimal top-9 contributes zero
    to either delta.
    """
    df = df.copy()
    base_pool = _build_rostered_pool(roster, projections_df)
    base_mean, base_std = _optimal_lineup_value(base_pool)
    league_mean, _league_std = _league_baseline_lineup()

    per_game_base_mean = base_mean / GAMES_PER_SEASON
    per_game_base_std = base_std / math.sqrt(GAMES_PER_SEASON)
    per_game_league_mean = league_mean / GAMES_PER_SEASON

    base_win_prob = _normal_cdf(
        per_game_base_mean, mean=per_game_league_mean, std=per_game_base_std
    )
    base_ceiling = per_game_base_mean + CEILING_Z * per_game_base_std

    delta_wp = []
    delta_ceiling = []
    for _, row in df.iterrows():
        candidate_pool = base_pool + [
            {
                "player_name": row["player_name"],
                "position": row["position"],
                "effective_points": row["effective_points"],
                "std_dev": row["std_dev"],
            }
        ]
        new_mean_season, new_std_season = _optimal_lineup_value(candidate_pool)
        new_mean = new_mean_season / GAMES_PER_SEASON
        new_std = new_std_season / math.sqrt(GAMES_PER_SEASON)
        new_win_prob = _normal_cdf(new_mean, mean=per_game_league_mean, std=new_std)
        new_ceiling = new_mean + CEILING_Z * new_std
        delta_wp.append((new_win_prob - base_win_prob) * 100.0)
        delta_ceiling.append(new_ceiling - base_ceiling)

    df["delta_win_prob_pct"] = delta_wp
    df["delta_ceiling_pts"] = delta_ceiling
    return df


def _rostered_team_positions(roster, projections_df: pd.DataFrame) -> list:
    """(team, position) pairs for every currently-rostered player -- computed
    once per pipeline run (not once per candidate) for the same-team stack
    penalty below.
    """
    if roster is None:
        return []
    pairs = []
    seen = set()
    for slot_players in roster.slots.values():
        for player_name in slot_players:
            if player_name in seen:
                continue
            seen.add(player_name)
            row = _lookup_player(projections_df, player_name)
            if row is None:
                continue
            pairs.append((row.get("team", ""), row["position"]))
    return pairs


def _same_team_stack_penalty(
    candidate_position: str, candidate_team, rostered_team_positions: list
) -> float:
    """Target-competition penalty for drafting a WR/TE who'd share an NFL
    team's finite target pool with a pass-catcher already on the roster.
    Only WR and TE can trigger or be matched here -- QB and RB pairings are
    intentionally excluded (see SAME_TEAM_WR_WR_PENALTY comment above).
    """
    if candidate_position not in ("WR", "TE") or not candidate_team or pd.isna(candidate_team):
        return 0.0
    penalty = 0.0
    for team, position in rostered_team_positions:
        if team != candidate_team:
            continue
        if candidate_position == "WR" and position == "WR":
            penalty += SAME_TEAM_WR_WR_PENALTY
        elif {candidate_position, position} == {"WR", "TE"}:
            penalty += SAME_TEAM_WR_TE_PENALTY
    return min(penalty, SAME_TEAM_STACK_PENALTY_CAP)


def _is_high_contingency_rb(row) -> bool:
    """RB whose own 85th-percentile ceiling is at least
    HIGH_CONTINGENCY_CEILING_MULTIPLIER x their own median projection --
    real injury-replacement/committee upside. In this variant std_dev comes
    directly from DraftSharks' own floor/ceiling spread, so this naturally
    selects genuinely high-variance backup-profile backs without needing an
    explicit "is a handcuff" flag or a synthetic volatility premium.
    """
    if row["position"] != "RB" or row["projected_points"] <= 0:
        return False
    return (row["std_dev"] / row["projected_points"]) >= HIGH_CONTINGENCY_STD_RATIO


def _pareto_frontier(df: pd.DataFrame) -> pd.DataFrame:
    """Players not dominated on BOTH RARC (value) and delta_ceiling_pts
    (upside) by any other player in the pool -- the two distinct strategic
    dimensions surfaced to the LLM, instead of a single blended score
    deciding everything before the LLM ever sees the board.
    """
    records = df.to_dict("records")
    frontier = []
    for i, a in enumerate(records):
        dominated = False
        for j, b in enumerate(records):
            if i == j:
                continue
            if (
                b["rarc_score"] >= a["rarc_score"]
                and b["delta_ceiling_pts"] >= a["delta_ceiling_pts"]
                and (b["rarc_score"] > a["rarc_score"] or b["delta_ceiling_pts"] > a["delta_ceiling_pts"])
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(a)
    return pd.DataFrame(frontier)


def _finalize_pareto_candidate(row) -> dict:
    return {
        "player_name": row["player_name"],
        "position": row["position"],
        "team": row.get("team", ""),
        "adp": None if pd.isna(row.get("adp")) else round(float(row["adp"]), 1),
        "projected_points": round(float(row["projected_points"]), 1),
        "std_dev": round(float(row["std_dev"]), 1),
        "rarc_score": round(float(row["rarc_score"]), 1),
        "delta_win_prob_pct": round(float(row["delta_win_prob_pct"]), 2),
        "delta_ceiling_pts": round(float(row["delta_ceiling_pts"]), 1),
        "p_avail_next_turn_pct": round(float(row["survival_prob"]) * 100.0, 1),
        "reach_penalty": round(float(row["reach_penalty"]), 2),
        "same_team_stack_penalty": round(float(row.get("same_team_stack_penalty", 0.0)), 2),
        "composite_score": round(float(row["composite_score"]), 2),
    }


def _label_candidates(candidates: list, current_pick_no: int) -> None:
    """Mutates each candidate dict in place with a short human-readable
    `strategic_profile` label -- context for the LLM prompt (and the UI),
    not used in any scoring decision.
    """
    if not candidates:
        return
    max_ceiling_idx = max(range(len(candidates)), key=lambda i: candidates[i]["delta_ceiling_pts"])
    max_rarc_idx = max(range(len(candidates)), key=lambda i: candidates[i]["rarc_score"])
    for i, candidate in enumerate(candidates):
        tags = []
        position = candidate["position"]
        adp = candidate["adp"]
        if (
            position == "RB"
            and candidate["projected_points"] > 0
            and (candidate["std_dev"] / candidate["projected_points"]) >= HIGH_CONTINGENCY_STD_RATIO
        ):
            tags.append("High-Contingency RB")
        elif position == "RB" and adp is not None and RB_DEAD_ZONE_ADP_START <= adp <= RB_DEAD_ZONE_ADP_END:
            tags.append("Dead Zone Volume RB")
        elif position == "WR":
            tags.append("High-Target PPR WR")
        elif position == "TE":
            tags.append("Positional Advantage TE")
        elif position == "QB":
            tags.append("QB Value")
        elif position in ("K", "DEF"):
            tags.append("Roster Completion")
        if candidate["reach_penalty"] > 0.5:
            tags.append("Reach Risk")
        elif adp is not None and adp - current_pick_no > 15:
            tags.append("Market Fall")
        if candidate.get("same_team_stack_penalty", 0.0) > 0:
            tags.append("Same-Team Stack Risk")
        if i == max_ceiling_idx:
            tags.append("High Ceiling")
        if i == max_rarc_idx:
            tags.append("Best Value (RARC)")
        candidate["strategic_profile"] = " / ".join(dict.fromkeys(tags)) or "Value Pick"


def generate_pareto_candidate_stream(
    drafted_player_names: set,
    csv_path: str = "data/projections_ds.csv",
    roster=None,
    round_num: int = 1,
    total_rounds: int = 15,
    current_pick_no: int = 1,
    picks_until_next_turn: int = 0,
    picks: list | None = None,
    teams: int = 12,
) -> list:
    """Main entry point: constructs a Pareto-optimal candidate stream
    (6-8 players, non-dominated on RARC vs. ceiling upside) instead of a
    fixed 3-archetype list. Identical pipeline to draft_math.py's version --
    only the variance source (`_real_std_dev` vs `_synthetic_std_dev`) and
    default csv_path differ.
    """
    projections_df = load_projections(csv_path)
    available_df = projections_df[~_drafted_mask(projections_df, drafted_player_names)]

    if not _kdef_unlocked(round_num, total_rounds):
        available_df = available_df[~available_df["position"].isin({"K", "DEF"})]

    available_df = _filter_hard_capped_positions(available_df, roster, round_num, total_rounds)

    required_positions = _final_round_required_positions(roster, round_num, total_rounds)
    if required_positions:
        forced_df = available_df[available_df["position"].isin(required_positions)]
        if not forced_df.empty:
            available_df = forced_df

    if available_df.empty:
        return []

    available_df = available_df.copy()
    available_df["effective_points"] = available_df["projected_points"]

    turn_gap = max(picks_until_next_turn, 0)
    if picks:
        demand_steps = compute_turn_gap_demand(picks, teams, total_rounds, current_pick_no, turn_gap)
    else:
        demand_steps = [set()] * turn_gap

    available_df = _apply_rarc(available_df, current_pick_no, demand_steps)
    available_df["reach_penalty"] = [
        _reach_penalty(a, s, current_pick_no)
        for a, s in zip(available_df["adp"].fillna(ADP_FALLBACK), available_df["sigma_adp"])
    ]
    available_df = _apply_portfolio_impact(available_df, roster, projections_df)

    rostered_team_positions = _rostered_team_positions(roster, projections_df)
    available_df["same_team_stack_penalty"] = [
        _same_team_stack_penalty(pos, team, rostered_team_positions)
        for pos, team in zip(available_df["position"], available_df["team"])
    ]

    available_df["composite_score"] = (
        W_RARC * available_df["rarc_score"]
        + W_DELTA_WP * available_df["delta_win_prob_pct"]
        + W_DELTA_CEILING * available_df["delta_ceiling_pts"]
        - W_REACH_PENALTY * available_df["reach_penalty"]
        - W_SAME_TEAM_STACK_PENALTY * available_df["same_team_stack_penalty"]
    )

    # Round 14 DEF guarantee: a structural override (guaranteed inclusion),
    # not a score multiplier -- proactively surfaces DEF a round before the
    # Round 15 force-fill above kicks in, without distorting anyone else's
    # composite score to do it.
    guaranteed = []
    if (
        round_num == total_rounds - 1
        and roster is not None
        and roster.position_counts.get("DEF", 0) == 0
    ):
        def_pool = available_df[available_df["position"] == "DEF"]
        if not def_pool.empty:
            guaranteed.append(def_pool.sort_values("composite_score", ascending=False).iloc[0])

    # Round 10+ high-contingency RB quota: same structural-override pattern
    # as the DEF guarantee above -- late-round WR mean projections routinely
    # outscore backup RBs on raw RARC, which would otherwise crowd every RB
    # out of the payload and send Tier 2 an all-WR stream with zero
    # contingency/handcuff-style options.
    if round_num >= HIGH_CONTINGENCY_ROUND_START:
        contingency_mask = available_df.apply(_is_high_contingency_rb, axis=1)
        contingency_pool = available_df[contingency_mask].sort_values(
            "composite_score", ascending=False
        )
        for _, row in contingency_pool.head(HIGH_CONTINGENCY_MIN_SLOTS).iterrows():
            guaranteed.append(row)

    ranked = available_df.sort_values("composite_score", ascending=False)
    frontier = _pareto_frontier(ranked.head(PARETO_POOL_CAP))
    frontier_ranked = (
        frontier.sort_values("composite_score", ascending=False) if not frontier.empty else frontier
    )

    selected: list = []
    selected_names: set = set()
    position_counts_selected: dict = {}

    def try_add(row) -> bool:
        name = row["player_name"]
        if name in selected_names:
            return False
        position = row["position"]
        if position_counts_selected.get(position, 0) >= POSITION_DIVERSITY_CAP:
            return False
        selected.append(row)
        selected_names.add(name)
        position_counts_selected[position] = position_counts_selected.get(position, 0) + 1
        return True

    for row in guaranteed:
        try_add(row)

    for _, row in frontier_ranked.iterrows():
        if len(selected) >= PARETO_STREAM_MAX:
            break
        try_add(row)

    if len(selected) < PARETO_STREAM_MIN:
        for _, row in ranked.iterrows():
            if len(selected) >= PARETO_STREAM_MAX:
                break
            try_add(row)

    # Guaranteed-inclusion picks (DEF completion, high-contingency RB quota)
    # are added first above so they're never dropped, but that means the
    # build order does NOT reflect quality -- sort here so the returned list
    # is genuinely best-first.
    selected.sort(key=lambda row: row["composite_score"], reverse=True)

    candidates = [_finalize_pareto_candidate(row) for row in selected]
    _label_candidates(candidates, current_pick_no)
    return candidates


def detect_roster_archetype(roster, round_num: int) -> str:
    """Lightweight descriptive label for the roster's current shape --
    context for the LLM prompt only, not used in any scoring decision.
    """
    if roster is None:
        return "Unknown"
    rb_count = roster.position_counts.get("RB", 0)
    if round_num <= 2 and rb_count >= 1:
        return "Hero_RB"
    if round_num >= 5 and rb_count == 0:
        return "Zero_RB"
    if round_num <= 4 and rb_count >= 3:
        return "Robust_RB"
    return "Balanced"
