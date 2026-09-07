"""Greedy weekly starting-lineup assignment. Same algorithm as
`_optimal_lineup_value`/`_build_rostered_pool` in
src/engine/draft_math_core.py -- top-N by projected points per fixed
position slot, then the single best remaining FLEX-eligible player to
FLEX -- generalized to read slot counts from a league's own
`roster_positions` (so it isn't hardcoded to one league's structure) and
extended to cover every fixed slot, including K/DEF, since a real
start/sit decision needs both unlike the draft engine's win-probability
model, which deliberately excludes them for an unrelated reason.
"""

from .bye_weeks import team_bye_week

FLEX_ELIGIBLE = {"RB", "WR", "TE"}

# Only the standard single-position slots plus the standard FLEX are
# handled -- SUPER_FLEX/WRRB_FLEX/etc. (other leagues' variants) aren't
# recognized yet and are silently ignored if present, same as any other
# unrecognized roster_positions entry (e.g. "BN", "IR", "TAXI").
FIXED_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def build_slot_requirements(roster_positions: list[str]) -> dict[str, int]:
    """Tallies non-bench starting-slot counts from Sleeper's raw
    roster_positions array, e.g. ["QB","RB","RB","WR","WR","TE","FLEX",
    "K","DEF","BN","BN",...] -> {"QB": 1, "RB": 2, "WR": 2, "TE": 1,
    "FLEX": 1, "K": 1, "DEF": 1}.
    """
    requirements: dict[str, int] = {}
    for slot in roster_positions:
        if slot in FIXED_POSITIONS or slot == "FLEX":
            requirements[slot] = requirements.get(slot, 0) + 1
    return requirements


def optimize_lineup(players: list[dict], slot_requirements: dict[str, int]) -> dict:
    """`players` is a list of {player_id, position, projected_points, ...}
    (any extra keys, e.g. name/team/injury_status, are carried through
    unchanged onto the returned starter/bench entries). Returns
    {starters: [...], bench: [...], total_projected_points}.
    """
    used: set[str] = set()
    starters: list[dict] = []

    for position in FIXED_POSITIONS:
        count = slot_requirements.get(position, 0)
        if count == 0:
            continue
        ranked = sorted(
            (p for p in players if p["position"] == position and p["player_id"] not in used),
            key=lambda p: -p["projected_points"],
        )
        for p in ranked[:count]:
            starters.append({**p, "slot": position})
            used.add(p["player_id"])

    flex_count = slot_requirements.get("FLEX", 0)
    if flex_count:
        flex_ranked = sorted(
            (p for p in players if p["position"] in FLEX_ELIGIBLE and p["player_id"] not in used),
            key=lambda p: -p["projected_points"],
        )
        for p in flex_ranked[:flex_count]:
            starters.append({**p, "slot": "FLEX"})
            used.add(p["player_id"])

    bench = [p for p in players if p["player_id"] not in used]
    total_projected_points = sum(p["projected_points"] for p in starters)

    return {
        "starters": starters,
        "bench": bench,
        "total_projected_points": total_projected_points,
    }


# Same pass-catcher pairing rule as _same_team_stack_penalty in
# src/engine/draft_math_core.py (WR-WR and WR-TE only) -- real fantasy
# research backs specifically these two pairings as genuine target
# competition; QB and RB pairings are deliberately excluded there for
# reasons that apply here too (QB+pass-catcher is a well-known positive
# correlation, RB production is driven by rushing/goal-line volume,
# largely orthogonal to passing-game targets). This is informational
# only here, not a scoring penalty -- see the plan's reasoning for why a
# penalty risks double-counting a correlation the projections may
# already reflect.
STACK_ELIGIBLE_POSITIONS = {"WR", "TE"}


def detect_same_team_stacks(starters: list[dict]) -> list[tuple[str, str]]:
    """Returns (player_id, player_id) pairs among the given starters that
    are same-team WR/WR or WR/TE -- i.e. at least one of the pair is a WR.
    A team with 3+ flagged pass-catchers among starters produces multiple
    pairs, one per combination, not just adjacent ones.
    """
    pass_catchers = [p for p in starters if p["position"] in STACK_ELIGIBLE_POSITIONS and p.get("team")]
    pairs = []
    for i, a in enumerate(pass_catchers):
        for b in pass_catchers[i + 1 :]:
            if a["team"] != b["team"]:
                continue
            if a["position"] == "WR" or b["position"] == "WR":
                pairs.append((a["player_id"], b["player_id"]))
    return pairs


# Statuses meaning "likely or definitely not playing" -- these get a loud
# starter warning. "Questionable" is common and usually means the player
# does play, so it stays a passive badge only (injury_status is already
# shown on every player row regardless of this set).
INJURY_WARNING_STATUSES = {"Out", "Doubtful", "IR", "PUP", "Suspended"}


def is_injury_warning(injury_status: str | None) -> bool:
    return injury_status in INJURY_WARNING_STATUSES


def classify_unresolved_player(player_id: str, season: str, week: int) -> str:
    """A rostered player missing a projection row this week is either on
    a bye or genuinely unmodeled by Sleeper. We can only confirm "bye"
    for DEF entries, whose player_id is literally its team code (Sleeper's
    convention) -- checking that code's bye week against the requested
    week needs no network call, just the static table in bye_weeks.py.
    Skill-position players can't be confirmed this way (see bye_weeks.py's
    docstring for why) and fall back to "no_projection" -- in practice
    almost always a bye too, just not confirmable this cheaply.
    """
    if team_bye_week(season, player_id) == week:
        return "bye"
    return "no_projection"


def classify_unresolved_players(player_ids: list[str], season: str, week: int) -> list[dict]:
    return [
        {"player_id": player_id, "reason": classify_unresolved_player(player_id, season, week)}
        for player_id in player_ids
    ]


def build_alternate_lineup(
    players: list[dict], slot_requirements: dict[str, int], stacks: list[tuple[str, str]]
) -> dict | None:
    """A single deterministic diversification pass: for each flagged
    same-team pair, drops the lower-projected member from consideration
    and re-runs the same greedy optimizer on what's left -- pulling in
    the next-best alternative for that slot, if one exists. Not a
    recursive/iterative de-stacker (a replacement could theoretically
    still stack with something else); one pass covers the common case
    without the edge cases a fully general solver would need to handle.
    Returns None if there are no stacks to break (nothing to offer).
    """
    if not stacks:
        return None

    by_id = {p["player_id"]: p for p in players}
    excluded: set[str] = set()
    for a_id, b_id in stacks:
        lower_id = a_id if by_id[a_id]["projected_points"] <= by_id[b_id]["projected_points"] else b_id
        excluded.add(lower_id)

    alt_pool = [p for p in players if p["player_id"] not in excluded]
    result = optimize_lineup(alt_pool, slot_requirements)

    # The excluded player is still on the roster -- just not eligible to
    # start in this alternate lineup, not dropped entirely. optimize_lineup
    # only saw alt_pool, so its own bench list is missing them; rebuild
    # bench against the full roster instead.
    starter_ids = {p["player_id"] for p in result["starters"]}
    result["bench"] = [p for p in players if p["player_id"] not in starter_ids]
    result["swapped_out"] = sorted(excluded)
    return result
