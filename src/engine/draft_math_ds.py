"""Draft valuation engine -- DraftSharks (DS) variant.

A thin wrapper around the shared engine in `draft_math_core.py` -- see that
file's own module docstring for the full RARC/Pareto architecture and every
rule that's identical across RB/DS/FP/SL, and for the reasoning behind
consolidating those four into a shared core this session.

This file's own job is just two things: point at DraftSharks' CSV
(`data/projections_ds.csv`) and supply `_real_std_dev` below -- DraftSharks
is the only source with real per-player floor/ceiling projections, so
unlike the other three variants (which all use the shared core's synthetic
heuristic), this one derives real variance directly from that data instead
of guessing.

Two DraftSharks columns were deliberately left OUT of this variant despite
being available in the CSV, to avoid double-counting or scope creep:
- strength_of_schedule: a real projection model should already reflect a
  player's actual opponents, so this is presumed already baked into
  projected_points/consensus_projection rather than a separate signal.
- injury_risk_pct: DraftSharks defines floor as worst-case "barring
  injury," so this is NOT redundant with floor/ceiling (it's a genuinely
  separate risk dimension) -- but it's still out of scope for this specific
  floor/ceiling swap and left for a future addition if wanted.
"""

import functools

import pandas as pd

from src.engine.draft_math_core import *  # noqa: F401,F403 -- re-exports every shared constant/function; see __all__ in draft_math_core.py
from src.engine.draft_math_core import (
    CEILING_Z,
    _apply_portfolio_impact as _core_apply_portfolio_impact,
    _compute_league_baseline_lineup,
    _label_candidates,
    generate_pareto_candidate_stream as _core_generate_pareto_candidate_stream,
)

DEFAULT_CSV_PATH = "data/projections_ds.csv"


def load_projections(csv_path: str = DEFAULT_CSV_PATH) -> pd.DataFrame:
    """floor_points/ceiling_points are backfilled to projected_points (i.e.
    zero implied variance) for any row missing them -- this is an
    external-data ingestion boundary, not an internal invariant, so a
    graceful degrade here is appropriate even though the current data pull
    has zero missing values for either column.
    """
    df = pd.read_csv(csv_path)
    df["floor_points"] = df["floor_points"].fillna(df["projected_points"])
    df["ceiling_points"] = df["ceiling_points"].fillna(df["projected_points"])
    return df


def _real_std_dev(row) -> float:
    """Real per-player variance, derived directly from DraftSharks' own
    floor_points -- deliberately DOWNSIDE-ONLY, not the full floor-to-
    ceiling spread: sigma = (projected_points - floor) / CEILING_Z. A
    symmetric sigma derived from the full span ((ceiling - floor) /
    (2 * CEILING_Z), the original version of this formula) meant a player
    whose CEILING jumped up -- more breakout upside, not more bust risk --
    got a BIGGER variance penalty in RARC purely for having more upside,
    which is backwards for a risk-adjusted metric. Basing sigma on the
    floor distance alone makes it independent of ceiling entirely, so a
    high-ceiling player is no longer penalized for their own upside; that
    upside still shows up correctly elsewhere, via the separate
    delta_ceiling_pts portfolio-impact term. DraftSharks doesn't publish an
    exact percentile definition for floor, so CEILING_Z (already used
    elsewhere for the 85th-percentile portfolio-ceiling calc) is reused
    here as a symmetric assumption: floor sits CEILING_Z std devs below
    the mean.
    """
    return max(0.0, (row["projected_points"] - row["floor_points"]) / CEILING_Z)


@functools.lru_cache(maxsize=4)
def _league_baseline_lineup(csv_path: str = DEFAULT_CSV_PATH) -> tuple:
    return _compute_league_baseline_lineup(csv_path)


def _apply_portfolio_impact(df: pd.DataFrame, roster, projections_df: pd.DataFrame) -> pd.DataFrame:
    return _core_apply_portfolio_impact(df, roster, projections_df, _real_std_dev, _league_baseline_lineup)


def _finalize_pareto_candidate(row) -> dict:
    """DS's own version, not the shared core default -- adds floor_points/
    ceiling_points, which `_label_candidates`' High-Contingency RB tag needs
    (via `_is_high_contingency`'s direct-ceiling-ratio branch) and the
    shared core's default candidate dict doesn't carry.
    """
    return {
        "player_name": row["player_name"],
        "position": row["position"],
        "team": row.get("team", ""),
        "adp": None if pd.isna(row.get("adp")) else round(float(row["adp"]), 1),
        "floor_points": None if pd.isna(row.get("floor_points")) else round(float(row["floor_points"]), 1),
        "ceiling_points": None if pd.isna(row.get("ceiling_points")) else round(float(row["ceiling_points"]), 1),
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


def generate_pareto_candidate_stream(
    drafted_player_names: set,
    csv_path: str = DEFAULT_CSV_PATH,
    roster=None,
    round_num: int = 1,
    total_rounds: int = 15,
    current_pick_no: int = 1,
    picks_until_next_turn: int = 0,
    picks: list | None = None,
    teams: int = 12,
) -> list:
    return _core_generate_pareto_candidate_stream(
        drafted_player_names,
        csv_path,
        _real_std_dev,
        _finalize_pareto_candidate,
        _label_candidates,
        _league_baseline_lineup,
        roster=roster,
        round_num=round_num,
        total_rounds=total_rounds,
        current_pick_no=current_pick_no,
        picks_until_next_turn=picks_until_next_turn,
        picks=picks,
        teams=teams,
    )
