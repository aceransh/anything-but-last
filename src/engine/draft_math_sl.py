"""Draft valuation engine -- Sleeper (SL) variant.

A thin wrapper around the shared engine in `draft_math_core.py` -- see that
file's own module docstring for the full RARC/Pareto architecture and every
rule that's identical across RB/DS/FP/SL, and for the reasoning behind
consolidating those four into a shared core this session.

This file's only job: point at Sleeper's own CSV (`data/projections_sl.csv`,
sourced directly from Sleeper's public projections endpoint -- see
`src/api/update_data_sl.py`) and use the shared core's synthetic variance
heuristic, since Sleeper's projections payload has no floor/ceiling columns
either (same situation as RotoBaller/FantasyPros). Nothing else differs
from `draft_math_rb.py`/`draft_math_fp.py` -- confirmed via full-file diff
before and after this refactor.
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

DEFAULT_CSV_PATH = "data/projections_sl.csv"


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
