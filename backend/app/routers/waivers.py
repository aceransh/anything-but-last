"""FAAB waiver bid valuation (on-demand board) + event-driven alert scan.
See CLAUDE.md's "FAAB Waiver Bid Valuation" section and the research PDF's
§4 for the math this implements and where it deliberately diverges.

Two routers in this file: `router` (mounted under /leagues, JWT-authed like
every other feature) for the on-demand board and the alert inbox, and
`internal_router` (mounted at the app root) for the scheduled scan -- that
one has no end-user session, so it's guarded by a shared secret header
instead of get_current_user.
"""

import logging
import secrets
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from .. import draftsharks, waiver_math
from ..config import get_settings
from ..db import get_supabase
from ..deps import UserContext, get_current_user
from ..lineup_math import build_slot_requirements
from ..schemas import WaiverAlert, WaiverBoardResponse, WaiverScanResponse, WaiverTarget
from ..trade_finder import player_marginal_value
from .leagues import get_owned_league

logger = logging.getLogger(__name__)

router = APIRouter()
internal_router = APIRouter()

SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"
SLEEPER_TRENDING_ADD_URL = "https://api.sleeper.app/v1/players/nfl/trending/add"

FANTASY_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# Sleeper's own settings.waiver_type value for FAAB-budget leagues --
# confirmed live against the real test league (returns 2). 0/1 are
# rolling-priority/reverse-standings waivers, where a dollar bid is
# meaningless; the board still shows marginal-value ranking either way.
FAAB_WAIVER_TYPE = 2

# Bound the expensive per-candidate x per-rival marginal-value computation
# (see waiver_math.rank_waiver_targets) -- same top-N-shortlist pattern
# used everywhere else in this app (trade_finder's TOP_N_SINGLES, the
# matchup simulator's fixed trial counts). Trending free agents are sorted
# by real add count first, so this keeps the ones actually worth ranking.
TOP_N_WAIVER_TARGETS = 15

# Per-scan-run candidates for a single league's alert -- keeps one hyper-
# active league from spamming Discord or dominating the scan's runtime.
MAX_ALERTS_PER_LEAGUE_PER_RUN = 5


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


def _fetch_trending_adds(lookback_hours: int, limit: int) -> list[dict]:
    return _sleeper_get(
        SLEEPER_TRENDING_ADD_URL, params={"lookback_hours": lookback_hours, "limit": limit}
    )


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
        "projected_points": row.get("stats", {}).get("pts_ppr") or 0.0,
    }


def _unknown_stub(player_id: str) -> dict:
    # Same graceful-degradation stub used by trade.py/matchup.py for a
    # player missing this week's projection row.
    return {
        "player_id": player_id,
        "position": "UNKNOWN",
        "name": None,
        "team": None,
        "injury_status": None,
        "projected_points": 0.0,
    }


def _find_roster(rosters: list[dict], roster_id: int) -> dict | None:
    return next((r for r in rosters if r["roster_id"] == roster_id), None)


def _build_pool(player_ids: set[str], info_by_id: dict[str, dict]) -> list[dict]:
    return [info_by_id.get(pid) or _unknown_stub(pid) for pid in player_ids]


def _faab_remaining(league_settings: dict, roster: dict) -> tuple[int, int]:
    settings = league_settings.get("settings") or {}
    total = settings.get("waiver_budget") or 0
    used = (roster.get("settings") or {}).get("waiver_budget_used") or 0
    return total, max(0, total - used)


@router.get("/{league_id}/waivers", response_model=WaiverBoardResponse)
def get_waivers(
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
    is_faab_league = (league_settings.get("settings") or {}).get("waiver_type") == FAAB_WAIVER_TYPE

    sleeper_rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    num_teams = len(sleeper_rosters)
    own_roster = _find_roster(sleeper_rosters, own_roster_id)
    if own_roster is None:
        raise HTTPException(status_code=404, detail="Your claimed roster wasn't found in this league")

    all_rostered_ids = {pid for r in sleeper_rosters for pid in (r.get("players") or [])}

    trending = _fetch_trending_adds(lookback_hours=24, limit=75)
    free_agents = [t for t in trending if t["player_id"] not in all_rostered_ids]
    add_count_by_id = {t["player_id"]: t["count"] for t in free_agents}
    # Trim to the shortlist BEFORE the expensive per-candidate x per-rival
    # marginal-value pass below -- ranked by Sleeper's own real add count.
    free_agents = free_agents[:TOP_N_WAIVER_TARGETS]

    projections = _fetch_week_projections(season, week)
    info_by_id = {row.get("player_id"): _row_to_player(row) for row in projections}

    # The TRUE free-agent supply per position -- every projected player not
    # on any roster, not just this week's trending shortlist above (a
    # shortlist of ~15 players is too thin to estimate real scarcity from,
    # see waiver_math.rank_waiver_targets's docstring).
    free_agent_counts_by_position: dict[str, int] = {}
    for player_id, player in info_by_id.items():
        if player_id in all_rostered_ids or player["projected_points"] <= 0:
            continue
        free_agent_counts_by_position[player["position"]] = (
            free_agent_counts_by_position.get(player["position"], 0) + 1
        )

    candidates = [info_by_id.get(t["player_id"]) or _unknown_stub(t["player_id"]) for t in free_agents]
    own_roster_players = _build_pool(set(own_roster.get("players") or []), info_by_id)

    if source == "draftsharks":
        ds_rows = draftsharks.fetch_weekly_rows(week)
        candidates = draftsharks.apply_to_players(candidates, ds_rows)
        own_roster_players = draftsharks.apply_to_players(own_roster_players, ds_rows)

    rival_rosters: dict[int, dict] = {}
    for roster in sleeper_rosters:
        roster_id = roster["roster_id"]
        if roster_id == own_roster_id:
            continue
        _, rival_remaining = _faab_remaining(league_settings, roster)
        pool = _build_pool(set(roster.get("players") or []), info_by_id)
        if source == "draftsharks":
            pool = draftsharks.apply_to_players(pool, ds_rows)
        rival_rosters[roster_id] = {"players": pool, "faab_remaining": rival_remaining}

    faab_total, faab_remaining = _faab_remaining(league_settings, own_roster)

    ranked = waiver_math.rank_waiver_targets(
        candidates,
        own_roster_players,
        rival_rosters,
        slot_requirements,
        week,
        faab_total if is_faab_league else 0,
        faab_remaining if is_faab_league else 0,
        num_teams,
        free_agent_counts_by_position,
    )

    targets = [
        WaiverTarget(
            player_id=c["player_id"],
            position=c["position"],
            projected_points=c["projected_points"],
            name=c.get("name"),
            team=c.get("team"),
            injury_status=c.get("injury_status"),
            add_count=add_count_by_id.get(c["player_id"], 0),
            delta_v=c["delta_v"],
            roi_temporal=c["roi_temporal"],
            scarcity=c["scarcity"],
            competitor_multiplier=c["competitor_multiplier"],
            recommended_bid=c["recommended_bid"] if is_faab_league else None,
        )
        for c in ranked
    ]

    return WaiverBoardResponse(
        week=week,
        is_faab_league=is_faab_league,
        faab_total=faab_total if is_faab_league else None,
        faab_remaining=faab_remaining if is_faab_league else None,
        targets=targets,
    )


@router.get("/{league_id}/waiver-alerts", response_model=list[WaiverAlert])
def list_waiver_alerts(league_id: str, user: UserContext = Depends(get_current_user)):
    league = get_owned_league(league_id, user.user_id)  # 404s if not the caller's own league

    result = (
        get_supabase()
        .table("waiver_alerts")
        .select("*")
        .eq("league_id", league_id)
        .order("alerted_at", desc=True)
        .limit(50)
        .execute()
    )
    rows = result.data
    if not rows:
        return []

    # Best-effort display enrichment (name/position/team) via this week's
    # Sleeper projections -- the alerts table itself only stores the
    # player_id, same "identity comes from Sleeper, not duplicated" pattern
    # as the rest of this app. An older alert for a player who's since gone
    # unprojected just shows player_id instead -- graceful, not an error.
    try:
        state = _sleeper_get(SLEEPER_STATE_URL)
        info_by_id = {
            row.get("player_id"): _row_to_player(row)
            for row in _fetch_week_projections(state["season"], state["week"])
        }
    except HTTPException:
        info_by_id = {}

    alerts = []
    for row in rows:
        info = info_by_id.get(row["sleeper_player_id"]) or {}
        alerts.append(
            WaiverAlert(
                **row,
                player_name=info.get("name"),
                position=info.get("position"),
                team=info.get("team"),
            )
        )
    return alerts


@router.post("/{league_id}/waiver-alerts/mark-read", status_code=204)
def mark_waiver_alerts_read(league_id: str, user: UserContext = Depends(get_current_user)):
    get_owned_league(league_id, user.user_id)  # 404s if not the caller's own league

    (
        get_supabase()
        .table("waiver_alerts")
        .update({"read_at": datetime.now(timezone.utc).isoformat()})
        .eq("league_id", league_id)
        .is_("read_at", "null")
        .execute()
    )
    # FastAPI defaults to a Content-Type: application/json header even with
    # no body -- some browsers' fetch() reject a 204 that carries that
    # header (no body allowed on 204 at all), failing with a bare
    # ERR_FAILED and no status code the frontend can see. An explicit empty
    # Response sends no Content-Type, which is what a real 204 needs.
    return Response(status_code=204)


def send_discord_alert(webhook_url: str, content: str) -> None:
    """Fire-and-forget: a broken/revoked webhook for one league shouldn't
    fail the scan for every other league, so failures are logged, not
    raised. Discord returns a normal HTTP response (401/404, not a
    connection error) for a bad/revoked webhook URL -- requests doesn't
    raise on that by itself, so the status code is checked explicitly,
    not just network-level exceptions.
    """
    try:
        response = requests.post(webhook_url, json={"content": content}, timeout=8)
        if not response.ok:
            logger.warning("Discord webhook rejected alert: %s %s", response.status_code, response.text[:200])
    except requests.RequestException:
        logger.warning("Discord webhook delivery failed", exc_info=True)


def _format_alert(player: dict, add_count: int, delta_v: float, bid_text: str) -> str:
    name = player.get("name") or player["player_id"]
    position = player.get("position") or "?"
    team = player.get("team") or "FA"
    return (
        f"🚨 **{name}** ({position}, {team}) is trending -- {add_count} adds in the last hour.\n"
        f"Would add **+{delta_v:.1f} pts** to your optimal lineup this week.{bid_text}"
    )


def _scan_league(league: dict, season: str, week: int, supabase) -> int:
    sleeper_league_id = league["sleeper_league_id"]
    own_roster_id = league["sleeper_roster_id"]
    webhook_url = league["discord_webhook_url"]

    trending = _fetch_trending_adds(lookback_hours=1, limit=50)
    if not trending:
        return 0

    sleeper_rosters = _sleeper_get(SLEEPER_ROSTERS_URL.format(league_id=sleeper_league_id))
    all_rostered_ids = {pid for r in sleeper_rosters for pid in (r.get("players") or [])}
    own_roster = _find_roster(sleeper_rosters, own_roster_id)
    if own_roster is None:
        return 0

    free_agents = [t for t in trending if t["player_id"] not in all_rostered_ids]
    if not free_agents:
        return 0

    already_alerted = {
        row["sleeper_player_id"]
        for row in (
            supabase.table("waiver_alerts")
            .select("sleeper_player_id")
            .eq("league_id", league["id"])
            .eq("week", week)
            .execute()
            .data
        )
    }
    new_candidates = [t for t in free_agents if t["player_id"] not in already_alerted][
        :MAX_ALERTS_PER_LEAGUE_PER_RUN
    ]
    if not new_candidates:
        return 0

    league_settings = _sleeper_get(SLEEPER_LEAGUE_URL.format(league_id=sleeper_league_id))
    slot_requirements = build_slot_requirements(league_settings.get("roster_positions", []))
    is_faab_league = (league_settings.get("settings") or {}).get("waiver_type") == FAAB_WAIVER_TYPE
    faab_total, faab_remaining = _faab_remaining(league_settings, own_roster)

    projections = _fetch_week_projections(season, week)
    info_by_id = {row.get("player_id"): _row_to_player(row) for row in projections}
    own_roster_players = _build_pool(set(own_roster.get("players") or []), info_by_id)
    avg_starter_value = waiver_math.average_starter_value(own_roster_players, slot_requirements)
    roi_temporal = waiver_math.compute_roi_temporal(week)

    # Same true-full-pool scarcity denominator as the on-demand board (see
    # rank_waiver_targets's docstring) -- not just this hour's trending list.
    free_agent_counts_by_position: dict[str, int] = {}
    for player_id, player in info_by_id.items():
        if player_id in all_rostered_ids or player["projected_points"] <= 0:
            continue
        free_agent_counts_by_position[player["position"]] = (
            free_agent_counts_by_position.get(player["position"], 0) + 1
        )
    num_teams = len(sleeper_rosters)

    sent = 0
    for t in new_candidates:
        player = info_by_id.get(t["player_id"]) or _unknown_stub(t["player_id"])
        delta_v = player_marginal_value(own_roster_players, slot_requirements, [player])

        # Only alert when this specific team's lineup would actually
        # improve -- a league-wide trending player who's useless to this
        # exact roster isn't worth a push notification.
        if delta_v <= 0:
            continue

        bid_text = ""
        if is_faab_league:
            scarcity = waiver_math.compute_position_scarcity(
                player["position"], slot_requirements, num_teams, free_agent_counts_by_position
            )
            # No rival-roster scan here (unlike the on-demand board) --
            # too expensive across every league x every candidate in one
            # scheduled run; competitor_multiplier=1.0 (baseline, no
            # competitive bump) keeps this a same-formula-minus-one-term
            # estimate, not a different formula. The precise,
            # competitor-aware number is what GET /waivers is for.
            bid = waiver_math.compute_faab_bid(
                delta_v, avg_starter_value, roi_temporal, scarcity, faab_total, faab_remaining, 1.0
            )
            bid_text = f" Suggested opening bid: ~${bid} FAAB."

        send_discord_alert(webhook_url, _format_alert(player, t["count"], delta_v, bid_text))
        supabase.table("waiver_alerts").insert(
            {"league_id": league["id"], "sleeper_player_id": t["player_id"], "week": week}
        ).execute()
        sent += 1

    return sent


@internal_router.post("/internal/waiver-scan", response_model=WaiverScanResponse)
def run_waiver_scan(x_cron_secret: str | None = Header(default=None, alias="X-Cron-Secret")):
    settings = get_settings()
    if not settings.cron_secret or not secrets.compare_digest(x_cron_secret or "", settings.cron_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")

    supabase = get_supabase()
    leagues = (
        supabase.table("leagues")
        .select("*")
        .not_.is_("discord_webhook_url", "null")
        .not_.is_("sleeper_roster_id", "null")
        .execute()
        .data
    )

    state = _sleeper_get(SLEEPER_STATE_URL)
    season, week = state["season"], state["week"]

    alerts_sent = 0
    for league in leagues:
        try:
            alerts_sent += _scan_league(league, season, week, supabase)
        except Exception:
            # One league's bad data/webhook shouldn't fail the whole scan.
            logger.exception("waiver scan failed for league %s", league.get("id"))
            continue

    return WaiverScanResponse(leagues_scanned=len(leagues), alerts_sent=alerts_sent)
