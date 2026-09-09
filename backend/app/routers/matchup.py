from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import draftsharks, matchup_math
from ..deps import UserContext, get_current_user
from ..lineup_math import build_slot_requirements
from ..schemas import MatchupSimulationResponse, PlayoffOddsResponse
from .leagues import get_owned_league

router = APIRouter()

SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_MATCHUPS_URL = "https://api.sleeper.app/v1/league/{league_id}/matchups/{week}"
SLEEPER_PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"

FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# Same upper bound used elsewhere in this app (trade.py, lineup.py's week
# query param) -- sum/simulate through the last week fantasy leagues
# typically score, regardless of a specific league's own playoff structure.
LAST_SCORED_WEEK = 18


def _sleeper_get(url: str, **kwargs) -> dict | list:
    try:
        response = requests.get(url, timeout=10, **kwargs)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Could not reach Sleeper") from exc
    response.raise_for_status()
    return response.json()


def _fetch_week_projections(season: str, week: int) -> list[dict]:
    return _sleeper_get(
        SLEEPER_PROJECTIONS_URL.format(season=season, week=week),
        params={"season_type": "regular", "position[]": FANTASY_POSITIONS},
    )


def _row_to_player(row: dict) -> dict:
    player_id = row.get("player_id")
    info = row.get("player") or {}
    name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or None
    points = row.get("stats", {}).get("pts_ppr")
    return {
        "player_id": player_id,
        "position": info.get("position") or (info.get("fantasy_positions") or [None])[0],
        "name": name,
        "team": info.get("team"),
        "injury_status": info.get("injury_status"),
        "projected_points": points or 0.0,
    }


@router.get("/{league_id}/matchup", response_model=MatchupSimulationResponse)
def get_matchup(
    league_id: str,
    week: int | None = Query(default=None, ge=1, le=18),
    source: str = Query(default="sleeper", pattern="^(sleeper|draftsharks)$"),
    user: UserContext = Depends(get_current_user),
):
    league = get_owned_league(league_id, user.user_id)
    own_roster_id = league.get("sleeper_roster_id")
    if own_roster_id is None:
        raise HTTPException(status_code=400, detail="Claim a roster in this league first")

    sleeper_league_id = league["sleeper_league_id"]
    state = _sleeper_get(SLEEPER_STATE_URL)
    season = state["season"]
    if week is None:
        week = state["week"]

    league_settings = _sleeper_get(SLEEPER_LEAGUE_URL.format(league_id=sleeper_league_id))
    slot_requirements = build_slot_requirements(league_settings.get("roster_positions", []))

    sleeper_rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    roster_player_ids = {r["roster_id"]: set(r.get("players") or []) for r in sleeper_rosters}

    matchups = _sleeper_get(SLEEPER_MATCHUPS_URL.format(league_id=sleeper_league_id, week=week))
    own_matchup = next((m for m in matchups if m["roster_id"] == own_roster_id), None)
    if own_matchup is None:
        raise HTTPException(status_code=404, detail="No matchup found for this week")
    opponent = next(
        (m for m in matchups if m["matchup_id"] == own_matchup["matchup_id"] and m["roster_id"] != own_roster_id),
        None,
    )
    if opponent is None:
        raise HTTPException(status_code=404, detail="No opponent found for this week (bye week?)")
    opponent_roster_id = opponent["roster_id"]

    projections = _fetch_week_projections(season, week)
    players_by_id = {row.get("player_id"): _row_to_player(row) for row in projections}

    def _pool(roster_id: int) -> list[dict]:
        return [players_by_id[pid] for pid in roster_player_ids.get(roster_id, set()) if pid in players_by_id]

    own_pool = _pool(own_roster_id)
    opponent_pool = _pool(opponent_roster_id)

    if source == "draftsharks":
        ds_rows = draftsharks.fetch_weekly_rows(week)
        own_pool = draftsharks.apply_to_players(own_pool, ds_rows)
        opponent_pool = draftsharks.apply_to_players(opponent_pool, ds_rows)

    result = matchup_math.simulate_matchup(
        own_pool, opponent_pool, slot_requirements, rng=np.random.default_rng()
    )

    return MatchupSimulationResponse(
        week=week,
        own_roster_id=own_roster_id,
        opponent_roster_id=opponent_roster_id,
        win_prob=result["win_prob_a"],
        opponent_win_prob=result["win_prob_b"],
        own_score=result["score_a"],
        opponent_score=result["score_b"],
        own_starters=result["starters_a"],
        opponent_starters=result["starters_b"],
    )


@router.get("/{league_id}/playoff-odds", response_model=PlayoffOddsResponse)
def get_playoff_odds(
    league_id: str,
    source: str = Query(default="sleeper", pattern="^(sleeper|draftsharks)$"),
    user: UserContext = Depends(get_current_user),
):
    league = get_owned_league(league_id, user.user_id)
    sleeper_league_id = league["sleeper_league_id"]

    state = _sleeper_get(SLEEPER_STATE_URL)
    season = state["season"]
    start_week = state["week"]

    league_settings = _sleeper_get(SLEEPER_LEAGUE_URL.format(league_id=sleeper_league_id))
    slot_requirements = build_slot_requirements(league_settings.get("roster_positions", []))
    settings = league_settings.get("settings") or {}
    playoff_teams = settings.get("playoff_teams") or 0
    playoff_week_start = settings.get("playoff_week_start")

    sleeper_rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    roster_player_ids = {r["roster_id"]: set(r.get("players") or []) for r in sleeper_rosters}
    standings_now = {
        r["roster_id"]: {
            "wins": r["settings"].get("wins", 0),
            "losses": r["settings"].get("losses", 0),
            "ties": r["settings"].get("ties", 0),
            "fpts": r["settings"].get("fpts", 0) + r["settings"].get("fpts_decimal", 0) / 100,
        }
        for r in sleeper_rosters
    }

    # Regular season runs through the week before playoffs start -- if
    # that's already behind us (or unknown), there's nothing left to
    # simulate and today's standings are the final answer.
    last_regular_week = (playoff_week_start - 1) if playoff_week_start else start_week - 1
    weeks = list(range(start_week, min(last_regular_week, LAST_SCORED_WEEK) + 1))

    remaining_weeks: dict[int, list[tuple[int, int]]] = {}
    weekly_starters: dict[int, dict[int, list[dict]]] = {}
    if weeks:
        with ThreadPoolExecutor(max_workers=6) as executor:
            weekly_matchups = list(
                executor.map(
                    lambda w: _sleeper_get(SLEEPER_MATCHUPS_URL.format(league_id=sleeper_league_id, week=w)),
                    weeks,
                )
            )
            weekly_projections = list(executor.map(lambda w: _fetch_week_projections(season, w), weeks))

        player_to_roster = {
            pid: rid for rid, ids in roster_player_ids.items() for pid in ids
        }

        for week, matchups in zip(weeks, weekly_matchups):
            by_matchup: dict[int, list[int]] = {}
            for m in matchups:
                by_matchup.setdefault(m["matchup_id"], []).append(m["roster_id"])
            remaining_weeks[week] = [
                (pair[0], pair[1]) for pair in by_matchup.values() if len(pair) == 2
            ]

        for week, projections in zip(weeks, weekly_projections):
            week_rosters: dict[int, list[dict]] = {rid: [] for rid in roster_player_ids}
            for row in projections:
                player_id = row.get("player_id")
                roster_id = player_to_roster.get(player_id)
                if roster_id is None:
                    continue
                player = _row_to_player(row)
                if player["position"] is None:
                    continue
                week_rosters[roster_id].append(player)
            weekly_starters[week] = week_rosters

        if source == "draftsharks":
            # Real weekly floor/ceiling for every remaining week -- fired in
            # an outer pool capped at 6 (fetch_weekly_rows is already
            # internally parallel, 5 requests each), same concurrency cap
            # already used for the Sleeper weekly-projection fetch above and
            # for the Trade Evaluator/Finder's identical per-week fetch.
            with ThreadPoolExecutor(max_workers=6) as executor:
                ds_rows_by_week = dict(zip(weeks, executor.map(draftsharks.fetch_weekly_rows, weeks)))
            for week, week_rosters in weekly_starters.items():
                ds_rows = ds_rows_by_week[week]
                for roster_id, pool in week_rosters.items():
                    week_rosters[roster_id] = draftsharks.apply_to_players(pool, ds_rows)

    odds = matchup_math.simulate_season(
        standings_now,
        remaining_weeks,
        weekly_starters,
        slot_requirements,
        playoff_teams,
        rng=np.random.default_rng(),
    )

    entries = [
        {
            "roster_id": rid,
            "current_wins": standings_now[rid]["wins"],
            "current_losses": standings_now[rid]["losses"],
            "current_ties": standings_now[rid]["ties"],
            "current_fpts": standings_now[rid]["fpts"],
            "playoff_odds": odds[rid],
        }
        for rid in standings_now
    ]
    entries.sort(key=lambda e: -e["playoff_odds"])

    return PlayoffOddsResponse(
        playoff_teams=playoff_teams, playoff_week_start=playoff_week_start, entries=entries
    )
