from concurrent.futures import ThreadPoolExecutor

import requests
from fastapi import APIRouter, Depends, HTTPException

from .. import trade_math
from ..deps import UserContext, get_current_user
from ..lineup_math import build_slot_requirements
from ..schemas import TradeEvaluateRequest, TradeEvaluateResponse, TradeRosterPlayer
from .leagues import get_owned_league

router = APIRouter()

SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"

FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# Sum through the last week fantasy leagues typically score, regardless of
# a specific league's own playoff_week_start -- same simplification as the
# week upper bound used elsewhere in this app (lineup.py's week query param).
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


def _find_roster(rosters: list[dict], roster_id: int) -> dict | None:
    return next((r for r in rosters if r["roster_id"] == roster_id), None)


def _row_to_player(row: dict) -> dict:
    player_id = row.get("player_id")
    info = row.get("player") or {}
    name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or None
    return {
        "player_id": player_id,
        "position": info.get("position") or (info.get("fantasy_positions") or [None])[0],
        "name": name,
        "team": info.get("team"),
        "injury_status": info.get("injury_status"),
        # This row's own week's points -- for the picker, that's this week's
        # (real, at-a-glance) value; for the ROS pool builder below, this
        # gets overwritten by the summed ROS total (see _build_pool).
        "projected_points": row.get("stats", {}).get("pts_ppr") or 0.0,
    }


@router.get("/{league_id}/trade/roster-players/{roster_id}", response_model=list[TradeRosterPlayer])
def get_roster_players(
    league_id: str,
    roster_id: int,
    user: UserContext = Depends(get_current_user),
):
    league = get_owned_league(league_id, user.user_id)
    sleeper_league_id = league["sleeper_league_id"]

    state = _sleeper_get(SLEEPER_STATE_URL)
    rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    roster = _find_roster(rosters, roster_id)
    if roster is None:
        raise HTTPException(status_code=404, detail="Roster not found in this league")
    roster_player_ids = set(roster.get("players") or [])

    projections = _fetch_week_projections(state["season"], state["week"])
    info_by_id = {}
    for row in projections:
        player_id = row.get("player_id")
        if player_id in roster_player_ids and player_id not in info_by_id:
            info_by_id[player_id] = _row_to_player(row)

    players = []
    for player_id in roster_player_ids:
        # On a bye (or otherwise unprojected) this week -- still a real,
        # selectable trade candidate, just without display info to show.
        players.append(
            info_by_id.get(player_id)
            or {
                "player_id": player_id,
                "position": "UNKNOWN",
                "name": None,
                "team": None,
                "injury_status": None,
                "projected_points": 0.0,
            }
        )
    return players


@router.post("/{league_id}/trade-evaluate", response_model=TradeEvaluateResponse)
def evaluate_trade(
    league_id: str,
    payload: TradeEvaluateRequest,
    user: UserContext = Depends(get_current_user),
):
    league = get_owned_league(league_id, user.user_id)
    sleeper_league_id = league["sleeper_league_id"]

    state = _sleeper_get(SLEEPER_STATE_URL)
    season = state["season"]
    start_week = state["week"]

    league_settings = _sleeper_get(SLEEPER_LEAGUE_URL.format(league_id=sleeper_league_id))
    slot_requirements = build_slot_requirements(league_settings.get("roster_positions", []))
    # Sleeper exposes this under the nested "settings" object, not top-level
    # like roster_positions -- e.g. 15 for a typical 14-week regular season.
    # Used to break out a "does this help during your actual playoffs"
    # breakdown, not to weight/multiply anything (see trade_math.evaluate_trade).
    playoff_start_week = (league_settings.get("settings") or {}).get("playoff_week_start")

    sleeper_rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    roster_player_ids: dict[int, set[str]] = {}
    for roster_id in payload.roster_ids:
        roster = _find_roster(sleeper_rosters, roster_id)
        if roster is None:
            raise HTTPException(status_code=404, detail=f"Roster {roster_id} not found in this league")
        roster_player_ids[roster_id] = set(roster.get("players") or [])

    weeks = list(range(start_week, LAST_SCORED_WEEK + 1))
    with ThreadPoolExecutor(max_workers=6) as executor:
        weekly_projections = list(executor.map(lambda w: _fetch_week_projections(season, w), weeks))

    player_to_roster: dict[str, int] = {
        player_id: roster_id for roster_id, ids in roster_player_ids.items() for player_id in ids
    }

    ros_points: dict[str, float] = {}
    info_by_id: dict[str, dict] = {}
    # Per-week rosters (not ROS-summed) -- this is what the verdict is
    # actually computed from, see trade_math.evaluate_trade's docstring
    # for why a season-total sum-then-optimize misses real value (byes,
    # streaky/complementary players with tied season totals).
    weekly_rosters: dict[int, dict[int, list[dict]]] = {}
    for week, projections in zip(weeks, weekly_projections):
        week_rosters: dict[int, list[dict]] = {roster_id: [] for roster_id in roster_player_ids}
        for row in projections:
            player_id = row.get("player_id")
            roster_id = player_to_roster.get(player_id)
            if roster_id is None:
                continue
            player = _row_to_player(row)
            if player["position"] is None:
                continue
            week_rosters[roster_id].append(player)

            points = row.get("stats", {}).get("pts_ppr")
            if points is not None:
                ros_points[player_id] = ros_points.get(player_id, 0.0) + points
            if player_id not in info_by_id:
                info_by_id[player_id] = player
        weekly_rosters[week] = week_rosters

    def _build_pool(player_ids: set[str]) -> list[dict]:
        pool = []
        for player_id in player_ids:
            # A rostered player can be missing from every fetched week (IR,
            # practice squad, deep bench) -- still a valid trade target
            # (e.g. trading for an injured player betting on their return),
            # so fall back to a zero-value, unplaceable stub rather than
            # dropping them and falsely erroring "not on your roster".
            info = info_by_id.get(player_id) or {
                "player_id": player_id,
                "position": "UNKNOWN",
                "name": None,
                "team": None,
                "injury_status": None,
                "projected_points": 0.0,
            }
            pool.append({**info, "projected_points": ros_points.get(player_id, 0.0)})
        return pool

    rosters = {roster_id: _build_pool(ids) for roster_id, ids in roster_player_ids.items()}

    try:
        result = trade_math.evaluate_trade(
            rosters,
            weekly_rosters,
            [move.model_dump() for move in payload.moves],
            slot_requirements,
            playoff_start_week=playoff_start_week,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TradeEvaluateResponse(
        start_week=start_week,
        end_week=LAST_SCORED_WEEK,
        playoff_start_week=playoff_start_week,
        **result,
    )
