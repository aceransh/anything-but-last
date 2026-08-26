from pathlib import Path

import pandas as pd
import requests

# The rankings page renders everything client-side via React; this is the JSON
# REST endpoint the page itself calls to fetch that data (found via the
# `window.rbRankings.proxy` config on the live page), used directly instead of
# parsing the rendered HTML.
# id=265860 -> All Positions / Overall board (not a single-position slice),
# spreadsheet=ppr -> PPR scoring, league=Overall -> the full-league consensus
# ranking set (this is what carries the "industry_avg" ADP consensus field
# per player, i.e. Average Draft Position). This board DOES include K/DST
# (verified directly against the live endpoint: 12 K + 16 DST rows, matching
# the counts in the backup CSV too) -- an earlier version of this script
# assumed it didn't and hard-filtered them out via VALID_POSITIONS, which is
# why K/DEF rows previously had to be added to projections_rb.csv by hand.
LIVE_API_URL = "https://www.rotoballer.com/wp-json/rb/v1/rankings"
LIVE_API_PARAMS = {"id": "265860", "spreadsheet": "ppr", "league": "Overall"}
BACKUP_CSV_CANDIDATES = [
    "data/rotoballer-Overall-ppr-proj-rankings.csv",
    str(Path.home() / "Downloads" / "rotoballer-Overall-ppr-proj-rankings.csv"),
]
OUTPUT_CSV = "data/projections_rb.csv"
MIN_VALID_PLAYERS = 200
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
# RotoBaller uses "DST" for defenses; the rest of this codebase (Sleeper pick
# metadata, roster.py, draft_math_rb.py) uses "DEF" -- normalized here so every
# downstream consumer only ever sees one code.
POSITION_ALIASES = {"DST": "DEF"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Corrects team assignments that lag behind real roster moves on the scraped source.
TEAM_CORRECTIONS = {
    "A.J. Brown": "NE",
}

# RotoBaller's DST rows use "JAC" for Jacksonville while every player row
# uses "JAX" -- normalized so within-file team matching (e.g. the same-team
# stack penalty in draft_math_rb.py) never silently misses a real match.
TEAM_CODE_ALIASES = {
    "JAC": "JAX",
}


def normalize(
    df: pd.DataFrame, name_col: str, pos_col: str, team_col: str, pts_col: str, adp_col: str
) -> pd.DataFrame:
    normalized = pd.DataFrame(
        {
            "player_name": df[name_col].astype(str).str.strip(),
            "position": df[pos_col].astype(str).str.strip().str.upper(),
            "team": df[team_col].astype(str).str.strip().str.upper(),
            "projected_points": pd.to_numeric(df[pts_col], errors="coerce"),
            "adp": pd.to_numeric(df[adp_col], errors="coerce"),
        }
    )
    normalized["position"] = normalized["position"].replace(POSITION_ALIASES)
    normalized["team"] = normalized["team"].replace(TEAM_CODE_ALIASES)
    normalized = normalized[normalized["position"].isin(VALID_POSITIONS)]
    normalized = normalized.dropna(subset=["projected_points"])
    normalized["team"] = normalized.apply(
        lambda row: TEAM_CORRECTIONS.get(row["player_name"], row["team"]), axis=1
    )
    return normalized.sort_values("projected_points", ascending=False).reset_index(drop=True)


def fetch_live() -> pd.DataFrame:
    response = requests.get(LIVE_API_URL, params=LIVE_API_PARAMS, headers=HEADERS, timeout=15)
    response.raise_for_status()

    records = response.json()["data"]
    rows = [
        {
            "player_name": record["player"]["name"],
            "position": record["position"],
            "team": record["team"],
            "projected_points": record["player"]["projections"]["ppr_points"],
            # "industry_avg" is RotoBaller's consensus Average Draft Position
            # field for this ranking set (cross-checked against the "ADP
            # (Average)" column in the backup CSV export -- same values).
            "adp": record["industry_avg"],
        }
        for record in records
        # A handful of deep-bench/rookie records (e.g. undrafted rookies RotoBaller
        # hasn't modeled yet) carry "projections": null. Skipping just those rows
        # (instead of letting one crash the whole fetch into the stale backup CSV
        # fallback) is what actually keeps this on the live data path.
        if record["player"]["projections"] is not None
    ]
    table = pd.DataFrame(rows)
    return normalize(table, "player_name", "position", "team", "projected_points", "adp")


def load_backup() -> pd.DataFrame:
    for path in BACKUP_CSV_CANDIDATES:
        if Path(path).exists():
            df = pd.read_csv(path)
            return normalize(df, "Player", "Pos", "Team", "PTS", "ADP (Average)")
    raise FileNotFoundError("No backup CSV found. Checked: " + ", ".join(BACKUP_CSV_CANDIDATES))


def build_draft_board() -> tuple:
    try:
        df = fetch_live()
        if len(df) >= MIN_VALID_PLAYERS:
            return df, "live"
        print(
            f"Live scrape returned only {len(df)} valid players "
            f"(< {MIN_VALID_PLAYERS}); falling back to backup CSV."
        )
    except Exception as e:
        print(f"Live scrape failed ({e}); falling back to backup CSV.")

    df = load_backup()
    return df, "backup"


def main() -> None:
    df, source = build_draft_board()
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} players to {OUTPUT_CSV} (source: {source})")
    print(df["position"].value_counts().to_string())


if __name__ == "__main__":
    main()
