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
# per player, i.e. Average Draft Position).
LIVE_API_URL = "https://www.rotoballer.com/wp-json/rb/v1/rankings"
LIVE_API_PARAMS = {"id": "265860", "spreadsheet": "ppr", "league": "Overall"}
BACKUP_CSV_CANDIDATES = [
    "data/rotoballer-Overall-ppr-proj-rankings.csv",
    str(Path.home() / "Downloads" / "rotoballer-Overall-ppr-proj-rankings.csv"),
]
OUTPUT_CSV = "data/projections.csv"
MIN_VALID_PLAYERS = 200
VALID_POSITIONS = {"QB", "RB", "WR", "TE"}

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
