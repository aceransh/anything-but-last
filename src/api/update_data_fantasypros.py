"""Fetches FantasyPros consensus rankings (ECR) + PPR season projections and
merges them into data/projections_fp.csv.

Both live on FantasyPros' own backing JSON API (AWS API Gateway + CloudFront,
per the response headers) rather than the rendered HTML pages:
- `{RANKINGS_API_URL}` -- rank-only ECR (Expert Consensus Rank), used here as
  a drop-in replacement for `adp` (see draft_math_fp.py's module docstring
  for why that's a reasonable substitution).
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
    """Fetches ECR + projected points for every position and merges them
    into the same 5-column schema the default/DraftSharks engines use:
    player_name, position, team, projected_points, adp (= ECR rank).
    """
    ecr = fetch_ecr()

    rows = []
    unmatched = 0
    for position in POSITIONS:
        points = fetch_projected_points(position)
        for name, (fpts, team) in points.items():
            key = (name, position)
            if key not in ecr:
                unmatched += 1
                continue
            _, adp = ecr[key]
            rows.append(
                {
                    "player_name": name,
                    "position": position,
                    "team": team,
                    "projected_points": fpts,
                    "adp": adp,
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
