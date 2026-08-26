"""Hybrid variant of test_draft_simulation.py -- same simulated 15-round,
12-team snake draft, but driving draft_math_hybrid.py against
data/projections_hybrid.csv instead of the default engine/CSV pair.
"""

from src.engine.draft_state import compute_pick_slot, picks_until_my_turn
from src.engine.draft_math_hybrid import (
    generate_pareto_candidate_stream,
    load_projections,
    normalize_name,
)
from src.engine.roster import Roster

TEAMS = 12
TOTAL_ROUNDS = 15
TOTAL_PICKS = TEAMS * TOTAL_ROUNDS
MY_SLOT = 1
CSV_PATH = "data/projections_hybrid.csv"

projections = load_projections(CSV_PATH)
bot_pool = projections.sort_values("adp").to_dict("records")

roster = Roster()
drafted_names: set = set()
my_picks: list[tuple[int, str, str]] = []  # (pick_no, name, position)

for pick_no in range(1, TOTAL_PICKS + 1):
    slot_on_clock, round_num, _ = compute_pick_slot(pick_no, TEAMS)

    if slot_on_clock == MY_SLOT:
        picks_until_next_turn = picks_until_my_turn(pick_no + 1, MY_SLOT, TEAMS)
        candidates = generate_pareto_candidate_stream(
            drafted_player_names=drafted_names,
            csv_path=CSV_PATH,
            roster=roster,
            round_num=round_num,
            total_rounds=TOTAL_ROUNDS,
            current_pick_no=pick_no,
            picks_until_next_turn=picks_until_next_turn,
            teams=TEAMS,
        )
        if not candidates:
            raise RuntimeError(f"No candidates available at pick {pick_no} -- pool exhausted")
        pick = max(candidates, key=lambda c: c["composite_score"])
        name, position = pick["player_name"], pick["position"]
        roster.add_player(name, position, round_num=round_num)
        my_picks.append((pick_no, name, position))
    else:
        # Bot: best remaining ADP, any position.
        drafted_normalized = {n for n, _ in drafted_names}
        best = next(
            p for p in bot_pool if normalize_name(p["player_name"]) not in drafted_normalized
        )
        name, position = best["player_name"], best["position"]

    drafted_names.add((normalize_name(name), position))

print("=== My draft picks (Hybrid engine) ===")
for pick_no, name, position in my_picks:
    round_num = (pick_no - 1) // TEAMS + 1
    print(f"  R{round_num:>2} (pick {pick_no:>3}): {name} ({position})")

print(f"\n=== Final roster position counts ===\n{roster.position_counts}")
print(f"\n=== Final slot assignment ===\n{roster.slots}")

counts = roster.position_counts
qb = counts.get("QB", 0)
rb = counts.get("RB", 0)
wr = counts.get("WR", 0)
te = counts.get("TE", 0)
k = counts.get("K", 0)
defense = counts.get("DEF", 0)

checks = [
    ("1 <= QB <= 2 (hard cap)", 1 <= qb <= 2, f"QB={qb}"),
    ("RB >= 2 (RB1/RB2 filled)", rb >= 2, f"RB={rb}"),
    ("WR >= 2 (WR1/WR2 filled)", wr >= 2, f"WR={wr}"),
    ("TE == 1 (single-TE lock, no dual-TE allocation)", te == 1, f"TE={te}"),
    ("K == 1", k == 1, f"K={k}"),
    ("DEF == 1", defense == 1, f"DEF={defense}"),
    ("15 total picks", sum(counts.values()) == TOTAL_ROUNDS, f"total={sum(counts.values())}"),
    ("no position over its hard max", qb <= 2 and te <= 2 and k <= 1 and defense <= 1, "QB/TE/K/DEF within hard caps"),
]

print("\n=== Verification ===")
all_passed = True
for label, passed, detail in checks:
    status = "PASS" if passed else "FAIL"
    if not passed:
        all_passed = False
    print(f"  [{status}] {label} ({detail})")

if not all_passed:
    raise SystemExit("SIMULATION FAILED: roster construction is not balanced")

print("\nSIMULATION PASSED (Hybrid engine): balanced Hero RB / PPR structure, zero positional over-saturation.")
