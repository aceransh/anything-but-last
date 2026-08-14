def compute_pick_slot(pick_no: int, teams: int) -> tuple:
    round_num = (pick_no - 1) // teams + 1
    pick_in_round = (pick_no - 1) % teams + 1
    slot = pick_in_round if round_num % 2 == 1 else teams - pick_in_round + 1
    return slot, round_num, pick_in_round


def picks_until_my_turn(current_pick_no: int, my_slot: int, teams: int) -> int:
    pick_no = current_pick_no
    while True:
        slot, _, _ = compute_pick_slot(pick_no, teams)
        if slot == my_slot:
            return pick_no - current_pick_no
        pick_no += 1


def format_pick_alert(pick: dict, my_draft_slot: int) -> str | None:
    metadata = pick.get("metadata")
    if not metadata:
        return None
    draft_slot = pick.get("draft_slot")
    # Mock drafts have no league/roster attached (no real team names to pull
    # from Sleeper -- `show_team_names` is off), so slots are labeled
    # positionally; this matches how Sleeper's own UI labels them too.
    team_name = "Your Team" if draft_slot == my_draft_slot else f"Team {draft_slot}"
    player_name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
    position = metadata.get("position", "?")
    team = metadata.get("team", "")
    return f"⚡ Pick #{pick.get('pick_no', '?')}: {team_name} drafted {player_name} ({position} - {team})"
