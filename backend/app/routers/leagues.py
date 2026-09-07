import requests
from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError

from ..db import get_supabase
from ..deps import UserContext, get_current_user
from ..schemas import LeagueCreate, LeagueOut, RosterClaim, RosterOption

router = APIRouter()

SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_USERS_URL = "https://api.sleeper.app/v1/league/{league_id}/users"


def get_owned_league(league_id: str, user_id: str) -> dict:
    """Fetches one of the caller's own league rows by its (our own, uuid)
    id -- 404s rather than 403s on a league that exists but belongs to
    someone else, so this endpoint doesn't confirm/deny another user's
    league ids. Shared by lineup.py, which needs the same lookup.
    """
    result = (
        get_supabase()
        .table("leagues")
        .select("*")
        .eq("id", league_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="League not found")
    return result.data[0]


@router.get("", response_model=list[LeagueOut])
def list_leagues(user: UserContext = Depends(get_current_user)):
    result = (
        get_supabase()
        .table("leagues")
        .select("*")
        .eq("user_id", user.user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post("", response_model=LeagueOut, status_code=201)
def create_league(payload: LeagueCreate, user: UserContext = Depends(get_current_user)):
    try:
        response = requests.get(
            SLEEPER_LEAGUE_URL.format(league_id=payload.sleeper_league_id), timeout=5
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Could not reach Sleeper") from exc

    # Sleeper returns HTTP 200 with a JSON `null` body for an unknown league
    # id, not a 404 -- both cases mean "not found" from here.
    league_data = response.json() if response.status_code == 200 else None
    if not league_data:
        raise HTTPException(status_code=404, detail="Sleeper league not found")

    row = {
        "user_id": user.user_id,
        "sleeper_league_id": payload.sleeper_league_id,
        "league_name": league_data.get("name") or "Unnamed League",
        "season": league_data.get("season") or "",
    }
    try:
        result = get_supabase().table("leagues").insert(row).execute()
    except APIError as exc:
        raise HTTPException(status_code=409, detail="League already connected") from exc

    return result.data[0]


@router.get("/{league_id}/rosters", response_model=list[RosterOption])
def list_rosters(league_id: str, user: UserContext = Depends(get_current_user)):
    league = get_owned_league(league_id, user.user_id)
    sleeper_league_id = league["sleeper_league_id"]

    try:
        rosters_response = requests.get(
            SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id), timeout=5
        )
        users_response = requests.get(
            SLEEPER_USERS_URL.format(league_id=sleeper_league_id), timeout=5
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Could not reach Sleeper") from exc

    rosters = rosters_response.json() or []
    users = users_response.json() or []
    display_name_by_owner = {u["user_id"]: u["display_name"] for u in users}

    return [
        RosterOption(
            sleeper_roster_id=roster["roster_id"],
            owner_display_name=display_name_by_owner.get(roster.get("owner_id"), "Unknown"),
        )
        for roster in rosters
    ]


@router.patch("/{league_id}", response_model=LeagueOut)
def claim_roster(league_id: str, payload: RosterClaim, user: UserContext = Depends(get_current_user)):
    get_owned_league(league_id, user.user_id)  # 404s if not the caller's own league

    result = (
        get_supabase()
        .table("leagues")
        .update({"sleeper_roster_id": payload.sleeper_roster_id})
        .eq("id", league_id)
        .eq("user_id", user.user_id)
        .execute()
    )
    return result.data[0]
