import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import draftsharks
from ..deps import UserContext, get_current_user
from ..lineup_math import (
    build_alternate_lineup,
    build_context_aware_lineup,
    build_slot_requirements,
    classify_unresolved_players,
    compute_context_weight,
    detect_same_team_stacks,
    is_injury_warning,
    optimize_lineup,
)
from ..schemas import AlternateLineup, ContextLineup, LineupResponse
from .leagues import get_owned_league

router = APIRouter()

SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"

# The position[] filter on Sleeper's projections endpoint doesn't fully
# filter (confirmed in src/api/update_data_sl.py) -- harmless here since
# results are filtered down to the roster's own player_ids afterward
# regardless, but kept narrow to avoid pulling every IDP/special-teamer.
FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def _sleeper_get(url: str, **kwargs) -> dict | list:
    try:
        response = requests.get(url, timeout=10, **kwargs)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Could not reach Sleeper") from exc
    response.raise_for_status()
    return response.json()


@router.get("/{league_id}/lineup", response_model=LineupResponse)
def get_lineup(
    league_id: str,
    week: int | None = Query(default=None, ge=1, le=18),
    source: str = Query(default="sleeper", pattern="^(sleeper|draftsharks)$"),
    context_win_prob: float | None = Query(default=None, ge=0.0, le=1.0),
    user: UserContext = Depends(get_current_user),
):
    league = get_owned_league(league_id, user.user_id)
    sleeper_league_id = league["sleeper_league_id"]
    sleeper_roster_id = league["sleeper_roster_id"]
    if sleeper_roster_id is None:
        raise HTTPException(
            status_code=400,
            detail="No roster claimed for this league yet -- claim your team first.",
        )

    state = _sleeper_get(SLEEPER_STATE_URL)
    season = state["season"]
    if week is None:
        week = state["week"]

    league_settings = _sleeper_get(SLEEPER_LEAGUE_URL.format(league_id=sleeper_league_id))
    slot_requirements = build_slot_requirements(league_settings.get("roster_positions", []))

    rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    roster = next((r for r in rosters if r["roster_id"] == sleeper_roster_id), None)
    if roster is None:
        raise HTTPException(status_code=404, detail="Roster no longer found in this league")
    roster_player_ids = set(roster.get("players") or [])

    projections = _sleeper_get(
        SLEEPER_PROJECTIONS_URL.format(season=season, week=week),
        params={"season_type": "regular", "position[]": FANTASY_POSITIONS},
    )

    players = []
    resolved_ids = set()
    for row in projections:
        player_id = row.get("player_id")
        if player_id not in roster_player_ids:
            continue
        points = row.get("stats", {}).get("pts_ppr")
        if points is None:
            continue  # no real projection this week (bye, or unmodeled) -- see plan's scope note
        info = row.get("player") or {}
        name = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip() or None
        players.append(
            {
                "player_id": player_id,
                "position": info.get("position") or row.get("player", {}).get("fantasy_positions", [None])[0],
                "projected_points": points,
                "name": name,
                "team": info.get("team"),
                "injury_status": info.get("injury_status"),
            }
        )
        resolved_ids.add(player_id)

    unresolved_players = classify_unresolved_players(
        sorted(roster_player_ids - resolved_ids), season, week
    )

    if source == "draftsharks":
        ds_rows = draftsharks.fetch_weekly_rows(week)
        players = draftsharks.apply_to_players(players, ds_rows)

    result = optimize_lineup(players, slot_requirements)
    stacks = detect_same_team_stacks(result["starters"])

    # Informational only -- flag each stacked starter with one teammate's
    # id (a 3-way stack has multiple pairs; showing one partner is enough
    # context for a badge, not an exhaustive listing).
    stack_partner: dict[str, str] = {}
    for a_id, b_id in stacks:
        stack_partner.setdefault(a_id, b_id)
        stack_partner.setdefault(b_id, a_id)
    for starter in result["starters"]:
        starter["same_team_stack_with"] = stack_partner.get(starter["player_id"])
        starter["injury_warning"] = is_injury_warning(starter.get("injury_status"))

    alternate = build_alternate_lineup(players, slot_requirements, stacks)
    alternate_lineup = AlternateLineup(**alternate) if alternate else None

    # Only meaningful with real floor/ceiling data -- on Sleeper's flat
    # synthetic-variance proxy every candidate's ranking is unchanged
    # regardless of w_context, so this would silently be a no-op (see
    # CLAUDE.md's writeup on this feature).
    context_lineup = None
    if context_win_prob is not None and source == "draftsharks":
        w_context = compute_context_weight(context_win_prob)
        context_lineup = ContextLineup(**build_context_aware_lineup(players, slot_requirements, w_context))

    return LineupResponse(
        week=week,
        starters=result["starters"],
        bench=result["bench"],
        total_projected_points=result["total_projected_points"],
        unresolved_players=unresolved_players,
        alternate_lineup=alternate_lineup,
        context_lineup=context_lineup,
    )
