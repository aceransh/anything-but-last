"""Fetches FantasyPros consensus rankings (ECR), real cross-platform ADP, and
PPR season projections, merging them into data/projections_fp.csv.

All three live on FantasyPros' own backing JSON API (AWS API Gateway +
CloudFront, per the response headers) rather than the rendered HTML pages:
- `{RANKINGS_API_URL}` -- called twice, with different `filters`/`type`
  params (see `fetch_ecr()` and `fetch_real_adp()`): once for rank-only ECR
  (Expert Consensus Rank), once for genuine cross-platform Average Draft
  Position. Earlier this session ECR was reused as an `adp` proxy, since
  real ADP wasn't known to be gettable without a login -- it turned out to
  be gettable from this same endpoint all along (see `fetch_real_adp()`'s
  docstring for how that was found), which frees ECR to be its own column
  instead. See draft_math_fp.py's module docstring for how the two are used
  differently downstream.
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

from collections import Counter

import pandas as pd
import requests

YEAR = 2026
RANKINGS_API_URL = f"https://api.fantasypros.com/v2/json/nfl/{YEAR}/consensus-rankings"
PROJECTIONS_API_URL = f"https://api.fantasypros.com/v2/json/nfl/{YEAR}/projections"
OUTPUT_CSV = "data/projections_fp.csv"

# See module docstring's Caveat section for what this is and how to refresh
# it if it ever stops working.
X_API_KEY = "zjxN52G3lP4fORpHRftGI2mTU8cTwxVNvkjByM3j"

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
# overall.php, which IS gated. Found by pulling that page's JS bundle and
# reading the exact call it makes: the SAME consensus-rankings endpoint as
# fetch_ecr(), just with a `filters` param selecting different "experts".
# FantasyPros models each fantasy platform's own live-draft data as an
# "expert" in their ranking system internally -- these three IDs (read
# directly out of the bundle's expert-ID lookup table) are ESPN, Yahoo, and
# Sleeper respectively. Filtering to just those turns the same `rank_ave`
# field that's ECR for human analysts into genuine cross-platform ADP.
REAL_ADP_EXPERT_FILTERS = "79:236:4350"

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
    Average Draft Position, not an ECR-of-human-analysts proxy. Uses
    `rank_ave` rather than `rank_ecr`: rank_ecr is a dense integer rank
    (ties broken arbitrarily, e.g. two players tied on rank_ave both get
    distinct consecutive rank_ecr values), while rank_ave is the actual
    averaged decimal draft position -- the same shape as RotoBaller's/
    DraftSharks' real `adp` columns elsewhere in this codebase.
    """
    params = {
        "type": "adp",
        "scoring": "PPR",
        "position": "ALL",
        "week": 0,
        "filters": REAL_ADP_EXPERT_FILTERS,
        "experts": "show",
    }
    response = requests.get(RANKINGS_API_URL, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    players = response.json()["players"]

    if len(players) < MIN_VALID_ROWS_PER_POSITION:
        raise FantasyProsAPIError(
            f"FantasyPros real-ADP API returned only {len(players)} players -- "
            "X_API_KEY may have rotated, or the ESPN/Yahoo/Sleeper expert IDs in "
            "REAL_ADP_EXPERT_FILTERS changed. See this module's docstring for how "
            "to recapture either from DevTools."
        )

    real_adp = {}
    for player in players:
        position = POSITION_ALIASES.get(player["player_position_id"], player["player_position_id"])
        real_adp[(player["player_name"], position)] = player["rank_ave"]
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
