"""Side-by-side comparison of the default engine (draft_math.py +
data/projections.csv, RotoBaller-sourced) vs. the DraftSharks variant
(draft_math_ds.py + data/projections_ds.csv, real floor/ceiling variance)
over two independent simulated 15-round, 12-team snake drafts.

Not a pass/fail test -- the two data sources have different ADP/points for
the same players, so bot behavior (best-ADP-remaining) and my own picks will
diverge for reasons beyond just the variance-model swap. This is a report,
not a regression gate; read it as "how differently do these two produce a
draft," not "which one is more correct."

Each simulation is a straight rerun of the logic in test_draft_simulation.py
/ test_draft_simulation_ds.py, factored into one function so both engines
run through identical draft-loop mechanics (same slot, same round math) --
only the engine module and CSV differ.
"""

import importlib

from src.engine.draft_state import compute_pick_slot, picks_until_my_turn
from src.engine.roster import Roster

TEAMS = 12
TOTAL_ROUNDS = 15
TOTAL_PICKS = TEAMS * TOTAL_ROUNDS
MY_SLOT = 1

ENGINES = [
    ("Default (RotoBaller)", "src.engine.draft_math", "data/projections.csv"),
    ("DraftSharks (DS)", "src.engine.draft_math_ds", "data/projections_ds.csv"),
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

    (label_a, _, _), (label_b, _, _) = ENGINES
    picks_a, counts_a = results[label_a]
    picks_b, counts_b = results[label_b]

    print(f"\n{'Round':<7}{label_a:<32}{label_b:<32}")
    print("-" * 71)
    for i in range(TOTAL_ROUNDS):
        pick_no_a, name_a, pos_a = picks_a[i]
        pick_no_b, name_b, pos_b = picks_b[i]
        round_num = i + 1
        left = f"{name_a} ({pos_a})"
        right = f"{name_b} ({pos_b})"
        match = " " if left == right else "*"
        print(f"R{round_num:<6}{left:<32}{right:<32}{match}")

    same_count = sum(
        1 for i in range(TOTAL_ROUNDS)
        if (picks_a[i][1], picks_a[i][2]) == (picks_b[i][1], picks_b[i][2])
    )
    print(f"\n{same_count}/{TOTAL_ROUNDS} picks matched exactly between the two engines.")

    print(f"\n{label_a} final roster: {counts_a}")
    print(f"{label_b} final roster: {counts_b}")


if __name__ == "__main__":
    main()
