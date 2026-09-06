import requests
from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError

from ..db import get_supabase
from ..deps import UserContext, get_current_user
from ..schemas import LeagueCreate, LeagueOut

router = APIRouter()

SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"


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
