import time

from src.engine.draft_math_rb import generate_pareto_candidate_stream
from src.engine.roster import Roster
from src.llm.client import generate_recommendation

roster = Roster()
roster.add_player("Bijan Robinson", "RB", round_num=1)
drafted = {"Bijan Robinson"}

candidates = generate_pareto_candidate_stream(
    drafted_player_names=drafted, roster=roster, round_num=2,
    total_rounds=15, current_pick_no=24, picks_until_next_turn=1,
)
draft_metadata = {
    "current_round": 2,
    "pick_number": 24,
    "picks_until_next_turn": 1,
    "roster_archetype_detected": "Hero_RB",
}

start = time.perf_counter()
recommendation = generate_recommendation(candidates, roster, draft_metadata, clock_seconds=30)
elapsed = time.perf_counter() - start

print(f"Recommended player: {recommendation.recommended_player}")
print(f"Alternatives: {recommendation.alternatives}")
print(f"Reason: {recommendation.short_reason}")
print(f"\nResponse time: {elapsed:.3f}s")
