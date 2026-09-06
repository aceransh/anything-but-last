"""Fetches FantasyPros consensus rankings (ECR), real cross-platform "Real-
Time ADP", and PPR season projections, merging them into
data/projections_fp.csv.

All three live on FantasyPros' own backing JSON APIs (AWS API Gateway +
CloudFront, per the response headers) rather than the rendered HTML pages:
- `{RANKINGS_API_URL}` -- rank-only ECR (Expert Consensus Rank). Earlier
  this session ECR was reused as an `adp` proxy, since real ADP wasn't
  known to be gettable without a login -- it's now its own separate
  column; see draft_math_fp.py's module docstring for how the two are used
  differently downstream.
- `{REAL_TIME_ADP_URL}` -- genuine cross-platform Average Draft Position,
  on a DIFFERENT host (`partners.fantasypros.com`, not `api.fantasypros.com`)
  than everything else here, found by reading the "Real-Time ADP" page's
  own JS bundle (`fantasypros.com/nfl/real-time-adp/ppr`). An earlier
  version of `fetch_real_adp()` called `{RANKINGS_API_URL}` filtered to
  ESPN/Yahoo/Sleeper's "expert" IDs -- that produced real-looking but
  materially wrong numbers (Yahoo's data wasn't even populated for most
  players, so it was silently just an ESPN/Sleeper average) because the
  page's actual "REAL-TIME" column reads a field (`rank_adp_raw`) that only
  exists in THIS endpoint's response, not the rankings one. This one
  blends 5 platforms (ESPN/CBS/RTSports/Fantrax/Sleeper, per its own
  `available_adp` field) with real recency-weighting (`rank_last_seven`/
  `rank_last_one` show the same field at different lookback windows --
  the literal source of the page's TREND columns), which is a materially
  different (and better) number than a flat expert-ID-filtered average.
- `{PROJECTIONS_API_URL}` -- full PPR season point projections per position,
  including `points_ppr` and a real team code for every position (DST
  included -- the old HTML scrape had no team code on DST rows at all).

**No session cookie needed for either.** A previous version of this script
scraped the rendered HTML pages directly: the rankings page was public, but
the projections pages only server-rendered 10 rows per position for an
anonymous request, requiring a logged-in session for the full table. This
JSON API returns full data for both with just the `X_API_KEY` header below
-- verified via a plain unauthenticated request (no cookies at all) that the
values match exactly what the cookie-gated HTML scrape produced (e.g. Josh
Allen 372.32 pts, Jahmyr Gibbs 372.74 pts).

**Caveat, not fully resolved:** `X_API_KEY` was captured from a logged-in
browser's DevTools Network tab. It has the shape of an AWS API-Gateway
usage-plan key (app-level, meant to be shipped in every visitor's frontend
JS for rate-limiting, not a personal auth token) -- and it worked
identically with zero cookies present, consistent with that theory -- but a
quick search of the anonymous page's inline scripts/JS bundles didn't turn
up the literal key string, so it's not confirmed to be a permanent public
constant. If this ever starts 401/403ing, capture a fresh value: DevTools ->
Network tab -> any request to api.fantasypros.com -> `x-api-key` request
header.
"""

import os
from collections import Counter

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

YEAR = 2026
RANKINGS_API_URL = f"https://api.fantasypros.com/v2/json/nfl/{YEAR}/consensus-rankings"
PROJECTIONS_API_URL = f"https://api.fantasypros.com/v2/json/nfl/{YEAR}/projections"
OUTPUT_CSV = "data/projections_fp.csv"

# See module docstring's Caveat section for what this is and how to refresh
# it if it ever stops working (DevTools -> Network -> api.fantasypros.com ->
# x-api-key request header).
X_API_KEY = os.environ.get("FANTASYPROS_X_API_KEY")

# Same aliases update_data.py already applies to RotoBaller data, for the
# same reasons: FantasyPros' rankings feed uses "DST" while the rest of the
# codebase uses "DEF", and uses "JAC" for Jacksonville while the rest of the
# codebase uses "JAX".
POSITION_ALIASES = {"DST": "DEF"}
TEAM_CODE_ALIASES = {"JAC": "JAX"}

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
# The API's own position codes match the HTML pages' slugs for every
# position except DST, whose API code is "DST" (aliased to "DEF" below,
# same as the rankings side).
API_POSITION_CODES = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DST"}

# A genuinely broken/rotated key or a reshaped API response would come back
# with far fewer players than any real position has (the shallowest, K, has
# 40+) -- this is a sanity check on the API contract, not a login-state
# check like the old HTML-scrape version had.
MIN_VALID_ROWS_PER_POSITION = 15

# FantasyPros' "Real-Time ADP" page (fantasypros.com/nfl/real-time-adp/ppr)
# is fully public -- no registration wall, unlike fantasypros.com/nfl/adp/
# overall.php, which IS gated. Its own JS bundle revealed the actual data
# flow: the page reads two API responses, keyed together by player_id. One
# is {RANKINGS_API_URL} (same as fetch_ecr()) for the per-platform ESPN/
# Yahoo/Sleeper individual-rank columns only. The other -- this one -- is
# what the page's main "REAL-TIME" column and TREND columns actually read
# from (`rank_adp_raw`, `rank_last_seven`, `rank_last_one`), on a DIFFERENT
# host entirely. `id=7556` is FantasyPros' internal ID for this specific
# blended feed (named "Real-Time ADP" right in its own response) -- found
# by reading the bundle's row-mapping code, not any public documentation.
REAL_TIME_ADP_URL = "https://partners.fantasypros.com/api/v1/expert-rankings.php"
REAL_TIME_ADP_EXPERT_ID = "7556"

HEADERS = {
    "x-api-key": X_API_KEY,
    "Origin": "https://www.fantasypros.com",
    "Referer": "https://www.fantasypros.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class FantasyProsAPIError(RuntimeError):
    """Raised when the FantasyPros API returns implausibly little data --
    most likely X_API_KEY has rotated/expired. See module docstring."""


def fetch_ecr() -> dict:
    """Returns {(player_name, position): (team, ecr_rank)} for the full
    consensus board (~500 players across all positions).
    """
    params = {
        "type": "draft",
        "scoring": "PPR",
        "position": "ALL",
        "week": 0,
        "experts": "available",
        "sport": "NFL",
    }
    response = requests.get(RANKINGS_API_URL, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    players = response.json()["players"]

    if len(players) < MIN_VALID_ROWS_PER_POSITION:
        raise FantasyProsAPIError(
            f"FantasyPros rankings API returned only {len(players)} players -- "
            "X_API_KEY may have rotated. See this module's docstring for how to refresh it."
        )

    ecr = {}
    for player in players:
        position = POSITION_ALIASES.get(player["player_position_id"], player["player_position_id"])
        team = TEAM_CODE_ALIASES.get(player["player_team_id"], player["player_team_id"])
        ecr[(player["player_name"], position)] = (team, player["rank_ecr"])
    return ecr


def fetch_real_adp() -> dict:
    """Returns {(player_name, position): real_adp} -- genuine cross-platform
    Average Draft Position (ESPN/CBS/RTSports/Fantrax/Sleeper, per this
    response's own `available_adp` field -- confirmed by inspecting a live
    response, not documented anywhere), not an ECR-of-human-analysts proxy.

    Uses `rank_adp_raw` (a real decimal draft position, e.g. "1.30"),
    falling back to the integer `rank` field for the rare row missing it --
    mirroring the Real-Time ADP page's own row-mapping code exactly
    (`adp: parseFloat(e.rank_adp_raw) || parseInt(e.rank)`), found by
    reading that page's JS bundle. This is deliberately NOT `fetch_ecr()`'s
    endpoint filtered to different experts (an earlier version of this
    function did that, using `rank_ave`) -- that produced real-looking but
    wrong numbers, because Yahoo's data wasn't even populated for most
    players in that response, silently collapsing to just an ESPN/Sleeper
    average. This endpoint is the actual source of the page's "REAL-TIME"
    column; verified directly against it (e.g. Jahmyr Gibbs 1.30, Bijan
    Robinson 2.20 -- matching the live page to one decimal place).
    """
    params = {
        "id": REAL_TIME_ADP_EXPERT_ID,
        "year": YEAR,
        "position": "ALL",
        "type": "adp",
        "scoring": "PPR",
    }
    response = requests.get(REAL_TIME_ADP_URL, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    players = response.json()["players"]

    if len(players) < MIN_VALID_ROWS_PER_POSITION:
        raise FantasyProsAPIError(
            f"FantasyPros Real-Time ADP API returned only {len(players)} players -- "
            "X_API_KEY may have rotated, or REAL_TIME_ADP_EXPERT_ID changed. See "
            "this module's docstring for how to recapture either from DevTools."
        )

    real_adp = {}
    for player in players:
        position = POSITION_ALIASES.get(player["player_positions"], player["player_positions"])
        raw = player.get("rank_adp_raw")
        adp = float(raw) if raw not in (None, "") else float(player["rank"])
        real_adp[(player["player_name"], position)] = adp
    return real_adp


def fetch_projected_points(position: str) -> dict:
    """Returns {player_name: (projected_points, team)} for one position's
    full PPR season projections.
    """
    params = {
        "type": "draft",
        "scoring": "PPR",
        "position": API_POSITION_CODES[position],
        "week": 0,
    }
    response = requests.get(PROJECTIONS_API_URL, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    players = response.json()["players"]

    if len(players) < MIN_VALID_ROWS_PER_POSITION:
        raise FantasyProsAPIError(
            f"FantasyPros projections API returned only {len(players)} players for "
            f"{position} -- X_API_KEY may have rotated. See this module's docstring "
            "for how to refresh it."
        )

    return {
        player["name"]: (
            player["stats"]["points_ppr"],
            TEAM_CODE_ALIASES.get(player["team_id"], player["team_id"]),
        )
        for player in players
    }


def build_draft_board() -> pd.DataFrame:
    """Fetches ECR + real ADP + projected points for every position and
    merges them into: player_name, position, team, projected_points, adp,
    ecr. `adp` is genuine cross-platform ADP (fetch_real_adp); `ecr` is kept
    as its own separate column rather than reused as an adp proxy -- see
    draft_math_fp.py's module docstring for how the two get used
    differently downstream (adp feeds the normal ADP-based math unchanged;
    ecr only powers a descriptive "Expert Buy-Low" tag, no scoring effect).
    A player can still be missing a real-ADP match even with an ECR match
    (the platforms' live-draft data isn't guaranteed to cover every name on
    the human-analyst consensus board) -- `adp` is left NaN for those rows,
    which the engine already handles gracefully (`.fillna(ADP_FALLBACK)`).
    """
    if not X_API_KEY:
        raise FantasyProsAPIError(
            "FANTASYPROS_X_API_KEY is not set. Capture a fresh value from "
            "DevTools -> Network tab -> any request to api.fantasypros.com "
            "-> x-api-key request header, then set it in .env."
        )
    ecr = fetch_ecr()
    real_adp = fetch_real_adp()

    rows = []
    unmatched = 0
    for position in POSITIONS:
        points = fetch_projected_points(position)
        for name, (fpts, team) in points.items():
            key = (name, position)
            if key not in ecr:
                unmatched += 1
                continue
            _, ecr_rank = ecr[key]
            rows.append(
                {
                    "player_name": name,
                    "position": position,
                    "team": team,
                    "projected_points": fpts,
                    "adp": real_adp.get(key, float("nan")),
                    "ecr": ecr_rank,
                }
            )

    if unmatched:
        print(f"Note: {unmatched} projected players had no ECR match (likely outside the top ~500 consensus board) and were dropped.")

    df = pd.DataFrame(rows)
    return df.sort_values("projected_points", ascending=False).reset_index(drop=True)


def main() -> None:
    df = build_draft_board()
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} players to {OUTPUT_CSV}")
    print(Counter(df["position"]))


if __name__ == "__main__":
    main()
