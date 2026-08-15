"""Side-by-side comparison of all three engine variants -- the default
(draft_math.py + data/projections.csv, RotoBaller-sourced), DraftSharks
(draft_math_ds.py + data/projections_ds.csv, real floor/ceiling variance),
and FantasyPros (draft_math_fp.py + data/projections_fp.csv, ECR-as-ADP) --
over three independent simulated 15-round, 12-team snake drafts.

Not a pass/fail test -- the three data sources have different ADP/points for
the same players, so bot behavior (best-ADP-remaining) and my own picks will
diverge for reasons beyond just the variance-model swap. This is a report,
not a regression gate; read it as "how differently do these three produce a
draft," not "which one is more correct."

Each simulation is a straight rerun of the logic in test_draft_simulation.py
/ test_draft_simulation_ds.py / test_draft_simulation_fp.py, factored into
one function so every engine runs through identical draft-loop mechanics
(same slot, same round math) -- only the engine module and CSV differ.

The comparison logic below is engine-count-agnostic (loops over ENGINES
rather than assuming exactly 2), so adding a 4th variant later is just
another tuple in the list.
"""

import importlib

from src.engine.draft_state import compute_pick_slot, picks_until_my_turn
from src.engine.roster import Roster

TEAMS = 12
TOTAL_ROUNDS = 15
TOTAL_PICKS = TEAMS * TOTAL_ROUNDS
MY_SLOT = 1
COL_WIDTH = 30

ENGINES = [
    ("Default (RotoBaller)", "src.engine.draft_math", "data/projections.csv"),
    ("DraftSharks (DS)", "src.engine.draft_math_ds", "data/projections_ds.csv"),
    ("FantasyPros (FP)", "src.engine.draft_math_fp", "data/projections_fp.csv"),
]


def run_simulation(module_name: str, csv_path: str) -> tuple[list[tuple[int, str, str]], dict]:
    """Runs one full simulated draft for the given engine module + CSV.
    Returns (my_picks, final_position_counts). Identical policy to
    test_draft_simulation.py: my team always takes the engine's own top
    composite_score candidate; bots draft best-ADP-remaining, position-
    agnostic, from that engine's own data.
    """
    engine = importlib.import_module(module_name)

    projections = engine.load_projections(csv_path)
    bot_pool = projections.sort_values("adp").to_dict("records")

    roster = Roster()
    drafted_names: set = set()
    my_picks: list[tuple[int, str, str]] = []

    for pick_no in range(1, TOTAL_PICKS + 1):
        slot_on_clock, round_num, _ = compute_pick_slot(pick_no, TEAMS)

        if slot_on_clock == MY_SLOT:
            picks_until_next_turn = picks_until_my_turn(pick_no + 1, MY_SLOT, TEAMS)
            candidates = engine.generate_pareto_candidate_stream(
                drafted_player_names=drafted_names,
                csv_path=csv_path,
                roster=roster,
                round_num=round_num,
                total_rounds=TOTAL_ROUNDS,
                current_pick_no=pick_no,
                picks_until_next_turn=picks_until_next_turn,
                teams=TEAMS,
            )
            if not candidates:
                raise RuntimeError(f"[{module_name}] No candidates available at pick {pick_no}")
            pick = max(candidates, key=lambda c: c["composite_score"])
            name, position = pick["player_name"], pick["position"]
            roster.add_player(name, position, round_num=round_num)
            my_picks.append((pick_no, name, position))
        else:
            drafted_normalized = {n for n, _ in drafted_names}
            best = next(
                p for p in bot_pool
                if engine.normalize_name(p["player_name"]) not in drafted_normalized
            )
            name, position = best["player_name"], best["position"]

        drafted_names.add((engine.normalize_name(name), position))

    return my_picks, dict(roster.position_counts)


def main() -> None:
    results = {}
    for label, module_name, csv_path in ENGINES:
        print(f"Running simulation: {label} ...")
        results[label] = run_simulation(module_name, csv_path)

    labels = [label for label, _, _ in ENGINES]
    picks = {label: results[label][0] for label in labels}
    counts = {label: results[label][1] for label in labels}

    header = "Round".ljust(7) + "".join(label.ljust(COL_WIDTH) for label in labels)
    print(f"\n{header}")
    print("-" * (7 + COL_WIDTH * len(labels)))
    for i in range(TOTAL_ROUNDS):
        round_num = i + 1
        cells = [f"{picks[label][i][1]} ({picks[label][i][2]})" for label in labels]
        all_match = len(set(cells)) == 1
        row = f"R{round_num:<6}" + "".join(cell.ljust(COL_WIDTH) for cell in cells)
        print(row + (" " if all_match else "*"))

    same_count = sum(
        1 for i in range(TOTAL_ROUNDS)
        if len({(picks[label][i][1], picks[label][i][2]) for label in labels}) == 1
    )
    print(f"\n{same_count}/{TOTAL_ROUNDS} picks matched exactly across all {len(labels)} engines.")

    print()
    for label in labels:
        print(f"{label} final roster: {counts[label]}")


if __name__ == "__main__":
    main()
