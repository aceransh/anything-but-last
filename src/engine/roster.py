ROSTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,
    "K": 1,
    "DEF": 1,
    "BN": 6,
}

FLEX_ELIGIBLE = {"RB", "WR", "TE"}
STARTING_POSITIONS = ("QB", "RB", "WR", "TE", "FLEX")


class Roster:
    def __init__(self):
        self.slots = {position: [] for position in ROSTER_SLOTS}
        self.position_counts: dict = {}
        # First round each position was drafted in -- lets draft_math_rb apply
        # round-dependent logic like the elite-vs-late-round QB1 constraint.
        self.position_first_round: dict = {}

    def add_player(self, player_name: str, position: str, round_num: int | None = None) -> str:
        self.position_counts[position] = self.position_counts.get(position, 0) + 1
        if round_num is not None:
            self.position_first_round[position] = min(
                round_num, self.position_first_round.get(position, round_num)
            )
        if len(self.slots.get(position, [])) < ROSTER_SLOTS.get(position, 0):
            self.slots[position].append(player_name)
            return position
        if position in FLEX_ELIGIBLE and len(self.slots["FLEX"]) < ROSTER_SLOTS["FLEX"]:
            self.slots["FLEX"].append(player_name)
            return "FLEX"
        self.slots["BN"].append(player_name)
        return "BN"

    def open_slots(self) -> dict:
        return {
            position: ROSTER_SLOTS[position] - len(filled)
            for position, filled in self.slots.items()
        }

    def starting_lineup_filled(self) -> bool:
        open_slots = self.open_slots()
        return all(open_slots.get(position, 0) <= 0 for position in STARTING_POSITIONS)

    def bench_has_room(self) -> bool:
        return self.open_slots().get("BN", 0) > 0

    def roster_needs_summary(self) -> str:
        open_slots = self.open_slots()
        needs = [
            f"{count} {position}"
            for position, count in open_slots.items()
            if count > 0 and position != "BN"
        ]
        if not needs:
            return "Starting lineup full, bench depth only"
        return "Need: " + ", ".join(needs)
