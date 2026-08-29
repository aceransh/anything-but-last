"""Offline prep utility -- NOT run during the draft loop (same rule as
update_data_rotoballer.py / update_data_draftsharks.py). Refreshes
data/projections_sl.csv from Sleeper's own public season-projections
endpoint -- the same platform this app polls for live draft picks
(src/api/sleeper.py), just a different endpoint, and no auth needed.

Two real gotchas found while building this (verified against a live pull
of the actual endpoint):

1. Despite passing position[]=QB/RB/WR/TE/K/DEF as query params, the
   response still includes non-standard positions (FB, P, CB, IDP-adjacent
   spillover) -- the same "the filter param doesn't fully filter" lesson as
   DraftSharks' IDP pagination gotcha. Must filter to STANDARD_POSITIONS
   client-side regardless of the request params.
2. `stats.adp_ppr` is present on essentially every row, but `stats.pts_ppr`
   (the season PPR point projection) is missing on the large majority of
   rows -- those are unsigned/inactive/deep-bench players RotoWire (the
   underlying projections provider, per each row's "company" field) hasn't
   modeled. Confirmed with a real example: Joe Mixon, a free agent as of
   this writing, has an adp_ppr but no pts_ppr. Rows must be filtered to
   pts_ppr is not None to get real draftable data -- this drops the raw
   ~3300-row response down to ~629 usable players.

Unlike every other source in this codebase, no team-code or position-code
aliasing is needed here: Sleeper's own `team` field already matches this
codebase's conventions (JAX not JAC, LV not LVR), and `position` is already
"DEF" not "DST". A small fraction of rows (~7% of the filtered pool) have
team=None -- a mix of genuine free agents and at least one apparent live
data gap for a rostered player -- left as-is; downstream engine code
already treats a missing team as "no same-team stack penalty applies."

DEF rows: `player.first_name` is the city (e.g. "Los Angeles") and
`player.last_name` is the mascot (e.g. "Rams"), so the standard
f"{first_name} {last_name}" join used for every position produces a clean
full team name with no special-casing needed.
"""

import pandas as pd
import requests

PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl"
SEASON = "2026"  # bump this each offseason
OUTPUT_CSV = "data/projections_sl.csv"

STANDARD_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
MIN_VALID_PLAYERS = 200  # sanity floor, mirrors update_data_draftsharks.py's MIN_VALID_PLAYERS

REQUEST_PARAMS = [
    ("season_type", "regular"),
    ("position[]", "QB"),
    ("position[]", "RB"),
    ("position[]", "WR"),
    ("position[]", "TE"),
    ("position[]", "K"),
    ("position[]", "DEF"),
    ("order_by", "adp_ppr"),
]


def fetch_all() -> pd.DataFrame:
    resp = requests.get(f"{PROJECTIONS_URL}/{SEASON}", params=REQUEST_PARAMS, timeout=20)
    resp.raise_for_status()
    records = resp.json()

    rows = []
    for record in records:
        player = record.get("player") or {}
        position = player.get("position")
        if position not in STANDARD_POSITIONS:
            continue

        stats = record.get("stats") or {}
        projected_points = stats.get("pts_ppr")
        if projected_points is None:
            continue

        player_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        rows.append(
            {
                "player_name": player_name,
                "position": position,
                "team": player.get("team"),
                "projected_points": projected_points,
                "adp": stats.get("adp_ppr"),
            }
        )

    df = pd.DataFrame(rows)
    df["projected_points"] = pd.to_numeric(df["projected_points"], errors="coerce")
    df["adp"] = pd.to_numeric(df["adp"], errors="coerce")
    df = df.dropna(subset=["projected_points"])
    return df.sort_values("projected_points", ascending=False).reset_index(drop=True)


def main() -> None:
    df = fetch_all()
    if len(df) < MIN_VALID_PLAYERS:
        raise RuntimeError(
            f"Only parsed {len(df)} valid players (< {MIN_VALID_PLAYERS}); "
            "Sleeper's projections endpoint likely changed shape -- check fetch_all()."
        )
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} players to {OUTPUT_CSV}")
    print(df["position"].value_counts().to_string())


if __name__ == "__main__":
    main()
