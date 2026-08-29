"""Draft valuation engine -- RotoBaller (RB) variant, the project's
default/base engine.

A thin wrapper around the shared engine in `draft_math_core.py`. This
file's own job is just two things: point at RotoBaller's CSV
(`data/projections_rb.csv`) and supply the synthetic variance heuristic
(`_synthetic_std_dev`, since RotoBaller has no real per-player variance
data). Every other rule -- RARC, survival probability, portfolio impact,
Pareto frontier, same-team stack penalty, hard roster-construction rules,
the QB1 opportunity-cost override, the scarcity-aware demand boost -- lives
in the shared core and is identical across this file and the DS/FP/SL
variants. See `draft_math_core.py`'s own module docstring for the full
RARC/Pareto architecture and the reasoning behind this consolidation.

This file (and DS/FP/SL) used to each be a ~1000-line, near-byte-identical
duplicate of one another. `draft_math_hybrid.py` is deliberately NOT part
of this consolidation -- it's a genuine fork now (dual-track ADP touches
several call sites, not a simple parameter swap), so it stays a full
standalone file.
"""

import functools

import pandas as pd

from src.engine.draft_math_core import *  # noqa: F401,F403 -- re-exports every shared constant/function; see __all__ in draft_math_core.py
from src.engine.draft_math_core import (
    _apply_portfolio_impact as _core_apply_portfolio_impact,
    _compute_league_baseline_lineup,
    _finalize_pareto_candidate,
    _label_candidates,
    _synthetic_std_dev,
    generate_pareto_candidate_stream as _core_generate_pareto_candidate_stream,
)

DEFAULT_CSV_PATH = "data/projections_rb.csv"


def load_projections(csv_path: str = DEFAULT_CSV_PATH) -> pd.DataFrame:
    return pd.read_csv(csv_path)


@functools.lru_cache(maxsize=4)
def _league_baseline_lineup(csv_path: str = DEFAULT_CSV_PATH) -> tuple:
    return _compute_league_baseline_lineup(csv_path)


def _apply_portfolio_impact(df: pd.DataFrame, roster, projections_df: pd.DataFrame) -> pd.DataFrame:
    return _core_apply_portfolio_impact(df, roster, projections_df, _synthetic_std_dev, _league_baseline_lineup)


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
