"""Static per-team bye-week table. Sleeper's player/projection data has no
bye_week field (confirmed in CLAUDE.md's Sleeper API research), so this is
hand-maintained per season from the NFL's published schedule -- add a new
top-level season key each year rather than overwriting this one.

Only used to confirm DEF byes exactly, since a DEF's Sleeper player_id is
already its team code. Skill-position players with no projection row are
NOT resolved against this table -- there's no cheap way to look up which
team a given skill player is on without Sleeper's full ~5MB player list,
and a rostered-but-genuinely-unmodeled skill player is rare enough not to
be worth that cost (see the lineup router's unresolved-player handling).

Source: nfl.com and fantasyfootballcalculator.com 2026 schedule releases,
cross-checked, 2026-09-07.
"""

BYE_WEEKS: dict[str, dict[str, int]] = {
    "2026": {
        "KC": 5,
        "CAR": 5,
        "MIA": 6,
        "CIN": 6,
        "DET": 6,
        "MIN": 6,
        "BUF": 7,
        "LAC": 7,
        "WAS": 7,
        "JAX": 7,
        "NYG": 8,
        "NO": 8,
        "SF": 8,
        "HOU": 8,
        "TEN": 9,
        "PIT": 9,
        "DEN": 10,
        "PHI": 10,
        "CHI": 10,
        "TB": 10,
        "NE": 11,
        "CLE": 11,
        "SEA": 11,
        "GB": 11,
        "ATL": 11,
        "LAR": 11,
        "IND": 13,
        "NYJ": 13,
        "LV": 13,
        "BAL": 13,
        "DAL": 14,
        "ARI": 14,
    }
}


def team_bye_week(season: str, team: str | None) -> int | None:
    """Returns the bye week for `team` in `season`, or None if unknown
    (unrecognized season, unrecognized team code, or team is None)."""
    if team is None:
        return None
    return BYE_WEEKS.get(season, {}).get(team)
