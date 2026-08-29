"""Draft valuation engine -- FantasyPros (FP) variant, the current default
data source (`DEFAULT_DATA_SOURCE = "fantasypros"` in `server.py`).

A thin wrapper around the shared engine in `draft_math_core.py` -- see that
file's own module docstring for the full RARC/Pareto architecture and every
rule that's identical across RB/DS/FP/SL, and for the reasoning behind
consolidating those four into a shared core this session.

This file's own job: point at FantasyPros' CSV (`data/projections_fp.csv`),
use the shared core's synthetic variance heuristic (FantasyPros has no
floor/ceiling data, only a 1-5 star Upside/Bust rating -- not a numeric
variance input), and -- the one real logic difference from RB/DS/SL --
supply its own `_finalize_pareto_candidate`/`_label_candidates` below,
since `_label_candidates` adds an "Expert Buy-Low" tag when a player's ECR
sits meaningfully better than their real ADP (`MARKET_EDGE_MIN_GAP`, see
below). Experts rating a player higher than the market is currently
drafting them is exactly the "market inefficiency" this engine already
exists to capture, just surfaced as its own explicit signal now that ECR
(`adp` here is genuine cross-platform Average Draft Position, see
`update_data_fantasypros.py`'s `fetch_real_adp()`) and ADP are no longer
the same number. Deliberately tag-only, no scoring effect -- see
`MARKET_EDGE_MIN_GAP`'s comment for why.
"""

import functools

import pandas as pd

from src.engine.draft_math_core import *  # noqa: F401,F403 -- re-exports every shared constant/function; see __all__ in draft_math_core.py
from src.engine.draft_math_core import (
    RB_DEAD_ZONE_ADP_END,
    RB_DEAD_ZONE_ADP_START,
    _apply_portfolio_impact as _core_apply_portfolio_impact,
    _compute_league_baseline_lineup,
    _is_high_contingency,
    _synthetic_std_dev,
    generate_pareto_candidate_stream as _core_generate_pareto_candidate_stream,
)

DEFAULT_CSV_PATH = "data/projections_fp.csv"


def load_projections(csv_path: str = DEFAULT_CSV_PATH) -> pd.DataFrame:
    return pd.read_csv(csv_path)


@functools.lru_cache(maxsize=4)
def _league_baseline_lineup(csv_path: str = DEFAULT_CSV_PATH) -> tuple:
    return _compute_league_baseline_lineup(csv_path)


def _apply_portfolio_impact(df: pd.DataFrame, roster, projections_df: pd.DataFrame) -> pd.DataFrame:
    return _core_apply_portfolio_impact(df, roster, projections_df, _synthetic_std_dev, _league_baseline_lineup)


def _finalize_pareto_candidate(row) -> dict:
    """FP's own version, not the shared core default -- adds the `ecr`
    field, which `_label_candidates` below needs for the Expert Buy-Low tag.
    """
    return {
        "player_name": row["player_name"],
        "position": row["position"],
        "team": row.get("team", ""),
        "adp": None if pd.isna(row.get("adp")) else round(float(row["adp"]), 1),
        "ecr": None if pd.isna(row.get("ecr")) else round(float(row["ecr"]), 1),
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


# How far ECR must sit ahead of real ADP (in ranks) before it's treated as a
# genuine "experts value this player higher than the market" signal rather
# than ordinary rank noise between two independently-computed rank orders.
# Deliberately tag-only (see _label_candidates' docstring) rather than a
# scored composite_score term: there's no backtested evidence yet for what
# weight would actually be correct, and guessing one would reintroduce
# exactly the kind of unvalidated arbitrary-weight problem the RARC rewrite
# was built to eliminate. Revisit once this tag has been observed across
# enough live drafts to judge whether it's meaningful.
MARKET_EDGE_MIN_GAP = 15.0


def _label_candidates(candidates: list, current_pick_no: int) -> None:
    """FP's own version, not the shared core default -- adds the "Expert
    Buy-Low" tag. Mutates each candidate dict in place with a short
    human-readable `strategic_profile` label -- context for the LLM prompt
    (and the UI), not used in any scoring decision.
    """
    if not candidates:
        return
    max_ceiling_idx = max(range(len(candidates)), key=lambda i: candidates[i]["delta_ceiling_pts"])
    max_rarc_idx = max(range(len(candidates)), key=lambda i: candidates[i]["rarc_score"])
    for i, candidate in enumerate(candidates):
        tags = []
        position = candidate["position"]
        adp = candidate["adp"]
        if position == "RB" and _is_high_contingency(
            candidate["projected_points"], candidate["std_dev"], candidate.get("floor_points"), candidate.get("ceiling_points")
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
        ecr = candidate.get("ecr")
        if ecr is not None and adp is not None and (adp - ecr) >= MARKET_EDGE_MIN_GAP:
            tags.append("Expert Buy-Low")
        if candidate.get("same_team_stack_penalty", 0.0) > 0:
            tags.append("Same-Team Stack Risk")
        if i == max_ceiling_idx:
            tags.append("High Ceiling")
        if i == max_rarc_idx:
            tags.append("Best Value (RARC)")
        candidate["strategic_profile"] = " / ".join(dict.fromkeys(tags)) or "Value Pick"


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
        _synthetic_std_dev,
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
