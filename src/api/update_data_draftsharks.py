"""Offline prep utility -- NOT run during the draft loop (same rule as
update_data.py). Refreshes data/projections_ds.csv from draftsharks.com's
PPR rankings page.

DraftSharks has no clean JSON API (unlike RotoBaller's discoverable
wp-json endpoint -- see update_data.py). Instead, the rankings table is
rendered from an HTML-fragment endpoint (Alpine.js + HTMX, not a headless
browser target): each player is a `<tbody data-player-row ...>` block with
clean `data-attribute`/`data-value` pairs per cell, which regex extraction
handles fine without needing a full DOM parser or a browser.

Two real gotchas found while building this (verified against a live,
full 250-player ranking pasted directly from the site by a human, matched
exactly against this script's output before shipping):

1. The raw HTML fragments blend IDP players (LB/DL/DB) in with standard
   positions, sorted together by "dsValue". The live page hides IDP rows
   client-side via `x-show="isVisibleRow($el)"` and keeps paginating past
   them until it has enough VISIBLE (standard) rows. A single page is NOT
   enough real standard-position players on its own -- this script has to
   paginate (offset=25, 250, 475, ...) filtering to standard positions each
   time, not just filter IDP out of the first page's results.
2. ADP is rendered as "round.pick" (e.g. "2.09"), not an overall pick
   number -- converted here via (round-1) * TEAMS + pick, cross-validated
   against RotoBaller's independent ADP for the same players (e.g. Derrick
   Henry: both sources agree on pick 21).
"""

import re

import pandas as pd
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
MAIN_URL = "https://www.draftsharks.com/rankings/ppr"
LOAD_ROWS_URL = "https://www.draftsharks.com/rankings/load-rows"
OUTPUT_CSV = "data/projections_ds.csv"

TEAMS = 12  # ADP round.pick -> overall pick conversion assumes a 12-team league, matching the rest of this codebase
STANDARD_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
TARGET_STANDARD_COUNT = 250
PAGE_SIZE = 225
MIN_VALID_PLAYERS = 200  # sanity floor, mirrors update_data.py's MIN_VALID_PLAYERS


def _parse_percent(value: str):
    if value is None:
        return None
    match = re.match(r"^(-?[\d.]+)%$", value.strip())
    return float(match.group(1)) if match else None


def parse_player_blocks(html: str) -> list:
    blocks = html.split("<tbody\n    data-player-row")[1:]
    rows = []
    for block in blocks:
        name_match = re.search(r'data-player-name="([^"]*)"', block)
        pos_match = re.search(r'data-fantasy-position="([^"]*)"', block)
        team_match = re.search(r'player-details-group__team-name">([^<]*)<', block)
        if not (name_match and pos_match and team_match):
            continue

        fields = {attr: val for val, attr in re.findall(r'data-value="([^"]*)" data-attribute="([^"]*)"', block)}

        adp_raw = fields.get("adp", "")
        adp_overall = None
        if re.match(r"^\d+\.\d+$", adp_raw):
            rnd, pick = adp_raw.split(".")
            adp_overall = (int(rnd) - 1) * TEAMS + int(pick)

        rows.append(
            {
                "player_name": name_match.group(1),
                "position": pos_match.group(1),
                "team": team_match.group(1),
                "projected_points": fields.get("fantasy_points"),  # DraftSharks' own median projection ("DS Proj")
                "consensus_projection": fields.get("consensus_projection"),  # blend of 30+ experts
                "floor_points": fields.get("floor_points"),  # worst-case, barring injury
                "ceiling_points": fields.get("ceiling_points"),  # best-case
                "ds_value": fields.get("dsValue"),  # DraftSharks' proprietary composite ranking score
                "games_played": fields.get("games_played"),
                "strength_of_schedule": _parse_percent(fields.get("strength_of_schedule")),
                "injury_risk_pct": _parse_percent(fields.get("player.sipPlayerProfile.injury_prob")),
                "adp": adp_overall,
            }
        )
    return rows


def fetch_all() -> pd.DataFrame:
    main_resp = requests.get(MAIN_URL, headers=HEADERS, timeout=15)
    main_resp.raise_for_status()
    all_rows = parse_player_blocks(main_resp.text)
    standard_rows = [r for r in all_rows if r["position"] in STANDARD_POSITIONS]

    offset = 25
    while len(standard_rows) < TARGET_STANDARD_COUNT:
        params = {
            "offset": str(offset),
            "limit": str(PAGE_SIZE),
            "fantasyPosition": "",
            "pprSuperflexSlug": "ppr",
            "sort": "-dsValue",
            "researchDepth": "rankings",
        }
        resp = requests.get(LOAD_ROWS_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        page_rows = parse_player_blocks(resp.text)
        if not page_rows:
            break
        standard_rows += [r for r in page_rows if r["position"] in STANDARD_POSITIONS]
        offset += PAGE_SIZE

    standard_rows = standard_rows[:TARGET_STANDARD_COUNT]

    df = pd.DataFrame(standard_rows)
    numeric_cols = (
        "projected_points",
        "consensus_projection",
        "floor_points",
        "ceiling_points",
        "ds_value",
        "games_played",
        "strength_of_schedule",
        "injury_risk_pct",
        "adp",
    )
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["projected_points"])
    return df.sort_values("projected_points", ascending=False).reset_index(drop=True)


def main() -> None:
    df = fetch_all()
    if len(df) < MIN_VALID_PLAYERS:
        raise RuntimeError(
            f"Only parsed {len(df)} valid players (< {MIN_VALID_PLAYERS}); "
            "draftsharks.com likely changed its markup -- check parse_player_blocks()."
        )
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} players to {OUTPUT_CSV}")
    print(df["position"].value_counts().to_string())


if __name__ == "__main__":
    main()
