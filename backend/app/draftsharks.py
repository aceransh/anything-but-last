"""Live fetch of DraftSharks' *weekly* rankings page
(draftsharks.com/weekly-rankings/{week}/ppr) -- a different page from the
draft copilot's draft-time scraper (src/api/update_data_draftsharks.py,
draftsharks.com/rankings/ppr), which is season-total/ADP-based and has no
per-week granularity. Confirmed live: same HTML-fragment rendering
architecture (no clean JSON API, `<tbody data-player-row>` blocks with
regex-extractable `data-attribute`/`data-value` pairs), just a different
page, param set, and field names -- this is a new scrape, not a reuse.

Deliberately duplicated from the draft engine's own parsing technique
rather than imported -- this app shares nothing at runtime with `src/`
(see CLAUDE.md's "Season Tools App" section), and it's a different page
anyway.

Reintroduces name-based player matching for the first time in this app
(CLAUDE.md: "Everything is keyed by Sleeper's own player_id ... sidesteps
the entire name-matching problem class the draft engine has to solve") --
but only for the ~18 players in one matchup, matched against Sleeper's
already-known name/position/team, not a blind N-source merge.
"""

import re
from concurrent.futures import ThreadPoolExecutor

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
MAIN_URL = "https://www.draftsharks.com/weekly-rankings/{week}/ppr"
LOAD_ROWS_URL = "https://www.draftsharks.com/weekly-rankings/load-rows"

STANDARD_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

# Confirmed live: the weekly board's IDP-blended row count (~878 total
# across offsets 25/250/475/700/925/1150) settles to ~440 standard-position
# rows by offset 700 -- these 4 pages (main + 3 load-rows calls, fetched in
# parallel) comfortably cover the entire standard-position board including
# all 32 DEF, so a fixed parallel fetch is simpler than adaptively paginating
# until a page comes back short.
LOAD_ROWS_OFFSETS = (25, 250, 475, 700)


def _normalize_name(name: str) -> str:
    name = name.lower().replace(".", "").replace("'", "")
    words = [w for w in name.split() if w not in SUFFIXES]
    return " ".join(words)


def parse_player_blocks(html: str) -> list[dict]:
    """Same block-splitting/regex-extraction technique as
    update_data_draftsharks.py's parse_player_blocks, adapted to this
    page's field names (weeklyFloorPts/weeklyCeilingPts/weeklyPts/
    consensus_projection/weekly3dPts instead of the draft page's
    floor_points/ceiling_points/fantasy_points/consensus_projection)."""
    blocks = html.split("<tbody\n    data-player-row")[1:]
    rows = []
    for block in blocks:
        name_match = re.search(r'data-player-name="([^"]*)"', block)
        pos_match = re.search(r'data-fantasy-position="([^"]*)"', block)
        team_match = re.search(r'player-details-group__team-name">([^<]*)<', block)
        if not (name_match and pos_match and team_match):
            continue

        fields = {attr: val for val, attr in re.findall(r'data-value="([^"]*)" data-attribute="([^"]*)"', block)}

        def _num(key: str) -> float | None:
            value = fields.get(key)
            try:
                return float(value) if value not in (None, "") else None
            except ValueError:
                return None

        rows.append(
            {
                "player_name": name_match.group(1),
                "position": pos_match.group(1),
                "team": team_match.group(1),
                "projected_points": _num("weekly3dPts"),
                "consensus_projection": _num("consensus_projection"),
                "floor_points": _num("weeklyFloorPts"),
                "ceiling_points": _num("weeklyCeilingPts"),
            }
        )
    return rows


def player_key(name: str, position: str, team: str | None) -> str | tuple[str, str]:
    """The lookup key both this module's own parsed rows and a caller's
    Sleeper-side player dicts should use to match against each other. DEF
    keys by team code (already identical between Sleeper and DraftSharks
    -- both e.g. "SEA"); everyone else keys by normalized name + position.
    """
    if position == "DEF":
        return team
    return (_normalize_name(name), position)


def _match_key(row: dict) -> str | tuple[str, str]:
    return player_key(row["player_name"], row["position"], row["team"])


def fetch_weekly_rows(week: int) -> dict[str | tuple[str, str], dict]:
    """Fetches this week's DraftSharks weekly board and returns it keyed
    for lookup against Sleeper roster players (see _match_key). A row
    missing its projected_points (weekly3dPts) is dropped -- nothing
    useful to offer a caller for that player.
    """
    urls_and_params = [(MAIN_URL.format(week=week), {})] + [
        (
            LOAD_ROWS_URL,
            {
                "offset": str(offset),
                "limit": "225",
                "fantasyPosition": "",
                "pprSuperflexSlug": "ppr",
                "sort": "-weekly3dPts",
                "week": str(week),
                "researchDepth": "rankings",
            },
        )
        for offset in LOAD_ROWS_OFFSETS
    ]

    def _fetch(url_params: tuple[str, dict]) -> str:
        url, params = url_params
        response = requests.get(url, headers=HEADERS, params=params, timeout=20)
        response.raise_for_status()
        return response.text

    with ThreadPoolExecutor(max_workers=len(urls_and_params)) as executor:
        pages = list(executor.map(_fetch, urls_and_params))

    rows_by_key: dict[str | tuple[str, str], dict] = {}
    for html in pages:
        for row in parse_player_blocks(html):
            # The fantasyPosition query param doesn't actually filter --
            # confirmed live (still returns RB as the first row) -- same
            # "the filter param doesn't fully filter" lesson as the draft
            # page and Sleeper's own weekly endpoint (see CLAUDE.md).
            if row["position"] not in STANDARD_POSITIONS:
                continue
            if row["projected_points"] is None:
                continue
            rows_by_key[_match_key(row)] = row
    return rows_by_key


def apply_to_players(players: list[dict], ds_rows: dict) -> list[dict]:
    """Overrides projected_points/floor/ceiling for whichever of the given
    (Sleeper-shaped) players match a DraftSharks row this week; a player
    with no match keeps their Sleeper values untouched (never dropped).
    Shared by routers/matchup.py and routers/lineup.py so this merge logic
    exists in exactly one place.
    """
    merged = []
    for p in players:
        key = player_key(p.get("name") or "", p["position"], p.get("team"))
        row = ds_rows.get(key)
        if row is None:
            merged.append(p)
            continue
        merged.append(
            {
                **p,
                "projected_points": row["projected_points"],
                "floor_points": row["floor_points"],
                "ceiling_points": row["ceiling_points"],
            }
        )
    return merged
