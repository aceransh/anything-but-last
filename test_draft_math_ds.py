"""DraftSharks (DS) variant of test_draft_math.py -- verifies draft_math_ds.py
against data/projections_ds.csv. Every rule here mirrors test_draft_math.py
except Rule 5, which tests `_real_std_dev` (floor/ceiling-derived variance)
instead of the original engine's `_synthetic_std_dev` heuristic -- the one
substantive difference between the two engines. See draft_math_ds.py's
module docstring for why.
"""

from src.engine.draft_math_ds import (
    ADP_FALLBACK,
    RB_DEAD_ZONE_ADP_END,
    RB_DEAD_ZONE_ADP_START,
    calculate_adp_std_dev,
    generate_pareto_candidate_stream,
    load_projections,
    normalize_name,
)
from src.engine.roster import Roster

# Rule 1: single-TE lock -- a 2nd TE never leaks into the stream through
# Round 14 with 1 TE already rostered, but reopens (emergency fill only) in
# the true final round.
roster = Roster()
roster.add_player("Travis Kelce", "TE")
roster.add_player("Bijan Robinson", "RB")
drafted = {"Travis Kelce", "Bijan Robinson"}

for round_num in (5, 8, 10, 14):
    candidates = generate_pareto_candidate_stream(
        drafted_player_names=drafted,
        roster=roster,
        round_num=round_num,
        total_rounds=15,
        current_pick_no=(round_num - 1) * 12 + 1,
        picks_until_next_turn=11,
    )
    positions = [c["position"] for c in candidates]
    assert "TE" not in positions, f"FAIL: 2nd TE leaked into candidates at round {round_num} with 1 TE already rostered"
print("PASS: zero 2nd TEs leaked into the Pareto stream in Rounds 1-14 with 1 TE already rostered.")

candidates_final = generate_pareto_candidate_stream(
    drafted_player_names=drafted, roster=roster, round_num=15, total_rounds=15,
    current_pick_no=169, picks_until_next_turn=11,
)
print(f"Round 15 (TE reopens): {[(c['player_name'], c['position']) for c in candidates_final]}")
print("PASS: TE hard-cap logic still gates on TE_FINAL_ROUND_MAX only in the true final round (no crash).")

# Rule 2: elite-tier QB1 (Rounds 1-6) permanently locks out a 2nd QB.
roster3 = Roster()
roster3.add_player("Josh Allen", "QB", round_num=2)
drafted3 = {"Josh Allen"}
for round_num in (5, 10, 12, 15):
    candidates3 = generate_pareto_candidate_stream(
        drafted_player_names=drafted3, roster=roster3, round_num=round_num,
        total_rounds=15, current_pick_no=(round_num - 1) * 12 + 1, picks_until_next_turn=11,
    )
    positions3 = [c["position"] for c in candidates3]
    assert "QB" not in positions3, f"FAIL: 2nd QB leaked in at round {round_num} despite elite-tier QB1 lock"
print("PASS: elite-tier QB1 (Round 2) permanently locks out a 2nd QB through Round 15.")

roster3b = Roster()
roster3b.add_player("Bo Nix", "QB", round_num=10)
candidates3b = generate_pareto_candidate_stream(
    drafted_player_names={"Bo Nix"}, roster=roster3b, round_num=11,
    total_rounds=15, current_pick_no=121, picks_until_next_turn=11,
)
print(f"Round 11, late-round QB1 (drafted round 10): {[(c['player_name'], c['position']) for c in candidates3b]}")
print("(2nd QB is allowed here -- no lock for a late-round QB1 -- shown for inspection, not asserted.)")

# Rule 3: Round 15 force-fill -- if only K/DEF starting slots are open, the
# candidate pool is hard-restricted to exactly those positions.
roster9 = Roster()
for pos, count in (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)):
    for i in range(count):
        roster9.add_player(f"{pos} Filler {i}", pos, round_num=1)
for i in range(6):
    roster9.add_player(f"Bench Filler {i}", "RB", round_num=1)
drafted9 = {f"{pos} Filler {i}" for pos, count in (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)) for i in range(count)}
drafted9 |= {f"Bench Filler {i}" for i in range(6)}
candidates9 = generate_pareto_candidate_stream(
    drafted_player_names=drafted9, roster=roster9, round_num=15,
    total_rounds=15, current_pick_no=169, picks_until_next_turn=11,
)
positions9 = {c["position"] for c in candidates9}
print(f"\nRound 15, only K/DEF starting slots open: candidate positions={positions9}")
assert positions9 <= {"K", "DEF"}, f"FAIL: Round 15 with only K/DEF open should force candidates into {{K, DEF}}, got {positions9}"
assert positions9, "FAIL: Round 15 with K/DEF both open should surface at least one candidate"
print("PASS: Round 15 force-fill restricts candidates to the still-open starting slots (K/DEF).")

# Rule 4: ADP std dev -- deeper ADP means a fuzzier (larger) std dev.
sigma_early = calculate_adp_std_dev(5.0)
sigma_late = calculate_adp_std_dev(150.0)
assert sigma_late > sigma_early, "FAIL: ADP std dev should grow with pick depth"
print(f"\nPASS: ADP std dev grows with draft depth (pick 5: {sigma_early:.2f}, pick 150: {sigma_late:.2f}).")

# Rule 5 (DS-specific): real per-player variance is derived from
# DraftSharks' own floor_points/ceiling_points spread, not a synthetic
# percentage-of-points heuristic. A player with a wide floor-ceiling gap
# should show a materially higher std_dev than one with a narrow gap, even
# at the same projected_points -- and the value should match the documented
# (ceiling - floor) / (2 * CEILING_Z) formula exactly.
from src.engine.draft_math_ds import CEILING_Z, _real_std_dev

wide_row = {"position": "RB", "projected_points": 200.0, "floor_points": 100.0, "ceiling_points": 300.0}
narrow_row = {"position": "RB", "projected_points": 200.0, "floor_points": 180.0, "ceiling_points": 220.0}
wide_std = _real_std_dev(wide_row)
narrow_std = _real_std_dev(narrow_row)
expected_wide_std = (300.0 - 100.0) / (2 * CEILING_Z)
assert wide_std > narrow_std, f"FAIL: wide floor-ceiling spread ({wide_std}) should exceed a narrow one's ({narrow_std})"
assert abs(wide_std - expected_wide_std) < 1e-9, f"FAIL: _real_std_dev should exactly match (ceiling-floor)/(2*CEILING_Z), got {wide_std} vs expected {expected_wide_std}"
print(f"PASS: real std_dev from floor/ceiling spread ({wide_std:.1f} wide vs {narrow_std:.1f} narrow) matches the documented formula.")

# Rule 6: reach penalty is continuous, not an instant max-out -- a mild
# (~1 pick) early selection should score much lower than a severe
# (~10+ round) reach.
from src.engine.draft_math_ds import REACH_PENALTY_CAP, _reach_penalty

sigma = calculate_adp_std_dev(50.0)
mild_reach = _reach_penalty(adp=51.0, sigma_adp=sigma, current_pick_no=50)
severe_reach = _reach_penalty(adp=200.0, sigma_adp=sigma, current_pick_no=50)
print(f"\nMild (1-pick) reach penalty: {mild_reach:.3f}; severe (150-pick) reach penalty: {severe_reach:.3f}")
assert mild_reach < 0.5, f"FAIL: a 1-pick-early selection shouldn't be heavily penalized, got {mild_reach}"
assert severe_reach == REACH_PENALTY_CAP, f"FAIL: an extreme reach should hit the cap, got {severe_reach}"
assert mild_reach < severe_reach, "FAIL: reach penalty should scale with reach severity"
print("PASS: reach penalty scales continuously with reach severity instead of saturating instantly.")

# Rule 7: portfolio impact -- a candidate genuinely worse than every current
# starter at every slot they're eligible for (own position AND FLEX) can't
# crack the optimal lineup, so contributes zero to both
# delta_win_prob_pct and delta_ceiling_pts.
from src.engine.draft_math_ds import _apply_portfolio_impact, _drafted_mask, _filter_hard_capped_positions

roster7 = Roster()
roster7.add_player("Trey McBride", "TE", round_num=9)  # strong TE fills the TE slot
roster7.add_player("Christian McCaffrey", "RB", round_num=1)  # fills RB1
roster7.add_player("Bijan Robinson", "RB", round_num=2)  # fills RB2
roster7.add_player("Jahmyr Gibbs", "RB", round_num=3)  # RB1/RB2 full -- this one fills FLEX
drafted7 = {"Trey McBride", "Christian McCaffrey", "Bijan Robinson", "Jahmyr Gibbs"}
df = load_projections()
available = df[~_drafted_mask(df, drafted7)].copy()
available["effective_points"] = available["projected_points"]
available["std_dev"] = 20.0
available = _apply_portfolio_impact(available, roster7, df)
bench_te = available[available["player_name"] == "Oronde Gadsden II"].iloc[0]  # deep-bench TE, well below McBride/Gibbs
assert roster7.open_slots()["FLEX"] == 0, "test setup assumption broken: FLEX should be full"
print(f"\nDeep-bench TE (worse than both TE starter and FLEX) portfolio impact: dWP={bench_te['delta_win_prob_pct']}, dCeil={bench_te['delta_ceiling_pts']}")
assert bench_te["delta_win_prob_pct"] == 0.0, "FAIL: a genuinely bench-only pickup should contribute 0 win-prob delta"
assert bench_te["delta_ceiling_pts"] == 0.0, "FAIL: a genuinely bench-only pickup should contribute 0 ceiling delta"
print("PASS: a player who can't crack the optimal lineup contributes zero marginal win-prob/ceiling value.")

# Rule 7b: greedy lineup optimizer -- a candidate who's BETTER than the
# current FLEX occupant (or any starter at their own position) correctly
# gets full starter credit instead of being evaluated as a bench asset,
# even if a literal draft-order slot assignment would've stuck them on the
# bench.
roster7b = Roster()
roster7b.add_player("Bijan Robinson", "RB", round_num=1)
roster7b.add_player("Jahmyr Gibbs", "RB", round_num=2)
roster7b.add_player("Jalen Coker", "WR", round_num=3)
roster7b.add_player("Jameson Williams", "WR", round_num=4)
roster7b.add_player("Rico Dowdle", "RB", round_num=5)  # RB1/RB2 full -- fills FLEX under FCFS
drafted7b = {"Bijan Robinson", "Jahmyr Gibbs", "Jalen Coker", "Jameson Williams", "Rico Dowdle"}
available7b = df[~_drafted_mask(df, drafted7b)].copy()
available7b["effective_points"] = available7b["projected_points"]
available7b["std_dev"] = 20.0
available7b = _apply_portfolio_impact(available7b, roster7b, df)
elite_wr_candidate = available7b[available7b["player_name"] == "Puka Nacua"].iloc[0]
print(f"Elite WR candidate (worth more than current FLEX starter Rico Dowdle) portfolio impact: dWP={elite_wr_candidate['delta_win_prob_pct']}, dCeil={elite_wr_candidate['delta_ceiling_pts']}")
assert elite_wr_candidate["delta_win_prob_pct"] > 0.0, "FAIL: a candidate that beats the current FLEX starter should get real starter credit, not be evaluated as bench-only"
print("PASS: the greedy optimizer correctly gives full starter credit to a candidate who beats the current FLEX occupant.")

# Rule 8: Pareto frontier -- a strictly dominated player (worse on both RARC
# and ceiling delta than another) is excluded from the frontier.
from src.engine.draft_math_ds import _pareto_frontier
import pandas as pd

frontier_input = pd.DataFrame([
    {"player_name": "A", "rarc_score": 50, "delta_ceiling_pts": 10},
    {"player_name": "B", "rarc_score": 40, "delta_ceiling_pts": 5},  # dominated by A
    {"player_name": "C", "rarc_score": 20, "delta_ceiling_pts": 30},  # non-dominated (higher ceiling)
])
frontier = _pareto_frontier(frontier_input)
frontier_names = set(frontier["player_name"])
print(f"\nPareto frontier of A/B/C: {frontier_names}")
assert "B" not in frontier_names, "FAIL: B is strictly dominated by A on both axes and should be excluded"
assert {"A", "C"} <= frontier_names, "FAIL: A and C are non-dominated and should both survive"
print("PASS: strictly-dominated candidates are excluded from the Pareto frontier.")

# Rule 9: opponent positional demand -- a team's own drafted picks
# correctly determine which starting positions they still need.
from src.engine.draft_math_ds import _team_open_starter_needs

fake_picks = [
    {"draft_slot": 3, "pick_no": 3, "metadata": {"first_name": "Josh", "last_name": "Allen", "position": "QB"}},
    {"draft_slot": 3, "pick_no": 15, "metadata": {"first_name": "Bijan", "last_name": "Robinson", "position": "RB"}},
]
needs = _team_open_starter_needs(fake_picks, draft_slot=3, teams=12)
print(f"\nTeam 3 (drafted QB + 1 RB) open starter needs: {needs}")
assert "QB" not in needs, "FAIL: team already has a QB, shouldn't show a QB need"
assert "RB" in needs, "FAIL: team only has 1 RB (RB2 slot still open), should show an RB need"
assert "WR" in needs and "TE" in needs, "FAIL: team hasn't drafted WR/TE yet, both should be needs"
print("PASS: opponent positional demand is derived correctly from real drafted picks.")

# Rule 10: full pipeline sanity -- returns 6-8 positionally-varied
# candidates for a normal mid-draft state, runs fast (well within the
# 30-second pick clock).
import time

df_full = load_projections()
top48 = df_full.sort_values("adp").head(48)
drafted_full = {(normalize_name(n), p) for n, p in zip(top48["player_name"], top48["position"])}
roster10 = Roster()
for _, row in df_full.sort_values("adp").iloc[[6, 17, 30, 41]].iterrows():
    roster10.add_player(row["player_name"], row["position"], round_num=1)
    drafted_full.add((normalize_name(row["player_name"]), row["position"]))

t0 = time.monotonic()
candidates10 = generate_pareto_candidate_stream(
    drafted_player_names=drafted_full, roster=roster10, round_num=5, total_rounds=15,
    current_pick_no=49, picks_until_next_turn=11, picks=[], teams=12,
)
elapsed = time.monotonic() - t0
print(f"\nRound 5 full pipeline: {len(candidates10)} candidates in {elapsed:.3f}s")
for c in candidates10:
    print(f"  {c['player_name']:22s} {c['position']:3s} rarc={c['rarc_score']:<7} comp={c['composite_score']:<7} {c['strategic_profile']}")
assert 1 <= len(candidates10) <= 8, f"FAIL: expected up to 8 candidates, got {len(candidates10)}"
assert elapsed < 5.0, f"FAIL: pipeline took {elapsed:.2f}s, too slow for a 30s pick clock"
positions10 = {c["position"] for c in candidates10}
assert len(positions10) >= 2, f"FAIL: expected positional variety in the stream, got only {positions10}"
print("PASS: full pipeline returns a fast, positionally-varied Pareto candidate stream.")

# Rule 11: Round 10+ high-contingency RB quota -- at least
# HIGH_CONTINGENCY_MIN_SLOTS of the stream are backup RBs whose own
# 85th-percentile ceiling clears HIGH_CONTINGENCY_CEILING_MULTIPLIER x
# their own median, driven here by real floor/ceiling data rather than a
# synthetic volatility premium.
from src.engine.draft_math_ds import HIGH_CONTINGENCY_MIN_SLOTS, HIGH_CONTINGENCY_ROUND_START

top132 = df_full.sort_values("adp").head(132)
drafted11 = {(normalize_name(n), p) for n, p in zip(top132["player_name"], top132["position"])}
roster11 = Roster()
for _, row in df_full.sort_values("adp").iloc[[6, 17, 30, 41, 54, 65, 78, 89, 102, 113, 126]].iterrows():
    roster11.add_player(row["player_name"], row["position"], round_num=1)
    drafted11.add((normalize_name(row["player_name"]), row["position"]))

candidates11 = generate_pareto_candidate_stream(
    drafted_player_names=drafted11, roster=roster11, round_num=HIGH_CONTINGENCY_ROUND_START + 2,
    total_rounds=15, current_pick_no=133, picks_until_next_turn=11, picks=[], teams=12,
)
high_contingency_count = sum(1 for c in candidates11 if "High-Contingency RB" in c["strategic_profile"])
print(f"\nRound {HIGH_CONTINGENCY_ROUND_START + 2}: {high_contingency_count} High-Contingency RB candidates out of {len(candidates11)}")
for c in candidates11:
    print(f"  {c['player_name']:22s} {c['position']:3s} {c['strategic_profile']}")
assert high_contingency_count >= HIGH_CONTINGENCY_MIN_SLOTS, (
    f"FAIL: expected at least {HIGH_CONTINGENCY_MIN_SLOTS} High-Contingency RB candidates in Round 10+, got {high_contingency_count}"
)
print(f"PASS: at least {HIGH_CONTINGENCY_MIN_SLOTS} High-Contingency RBs guaranteed in the Round 10+ stream.")

# Rule 12: the returned candidate stream is genuinely sorted best-first by
# composite_score, even when guaranteed-inclusion picks (Round 10+
# high-contingency RBs here) score far below the frontier.
scores11 = [c["composite_score"] for c in candidates11]
assert scores11 == sorted(scores11, reverse=True), (
    f"FAIL: candidate stream is not sorted best-first by composite_score: {scores11}"
)
print(f"\nCandidate stream composite scores (should be descending): {scores11}")
print("PASS: candidate stream is genuinely sorted best-first, including guaranteed-inclusion picks.")

# Rule 13: fallback_recommendation() picks the actual highest composite_score
# candidate, not just whatever happens to be first in the list.
from src.llm.client import fallback_recommendation

shuffled = [candidates11[-1], candidates11[0], candidates11[len(candidates11) // 2]]
fallback = fallback_recommendation(shuffled)
expected_best = max(shuffled, key=lambda c: c["composite_score"])
print(f"\nShuffled input first element: {shuffled[0]['player_name']} (comp={shuffled[0]['composite_score']})")
print(f"fallback_recommendation picked: {fallback.recommended_player} (expected: {expected_best['player_name']})")
assert fallback.recommended_player == expected_best["player_name"], (
    f"FAIL: fallback_recommendation picked {fallback.recommended_player} instead of the actual "
    f"best-scoring candidate {expected_best['player_name']}"
)
print("PASS: fallback_recommendation is robust to input order and always picks the true best candidate.")

# Rule 14: same-team non-QB stack penalty -- WR+WR (same team) gets the
# largest penalty, WR+TE a smaller one, RB pairings and QB stacks get none
# at all (a QB+same-team pass-catcher is a deliberate, desired strategy).
from src.engine.draft_math_ds import (
    SAME_TEAM_WR_TE_PENALTY,
    SAME_TEAM_WR_WR_PENALTY,
    _rostered_team_positions,
    _same_team_stack_penalty,
)

roster14 = Roster()
roster14.add_player("Rashee Rice", "WR", round_num=2)  # KC WR
pairs14 = _rostered_team_positions(roster14, load_projections())
wr_wr_penalty = _same_team_stack_penalty("WR", "KC", pairs14)
wr_te_penalty = _same_team_stack_penalty("TE", "KC", pairs14)
rb_penalty = _same_team_stack_penalty("RB", "KC", pairs14)
qb_penalty = _same_team_stack_penalty("QB", "KC", pairs14)
other_team_penalty = _same_team_stack_penalty("WR", "BUF", pairs14)
print(f"\nWith a KC WR already rostered: same-team WR={wr_wr_penalty}, TE={wr_te_penalty}, RB={rb_penalty}, QB={qb_penalty}, other-team WR={other_team_penalty}")
assert wr_wr_penalty == SAME_TEAM_WR_WR_PENALTY, f"FAIL: same-team WR+WR should be penalized at {SAME_TEAM_WR_WR_PENALTY}, got {wr_wr_penalty}"
assert wr_te_penalty == SAME_TEAM_WR_TE_PENALTY, f"FAIL: same-team WR+TE should be penalized at {SAME_TEAM_WR_TE_PENALTY}, got {wr_te_penalty}"
assert wr_wr_penalty > wr_te_penalty, "FAIL: same-team WR+WR should be penalized more heavily than WR+TE"
assert rb_penalty == 0.0, f"FAIL: RB pairings should never be penalized (not a real target-competition effect), got {rb_penalty}"
assert qb_penalty == 0.0, f"FAIL: QB stacks should never be penalized (deliberate positive-correlation strategy), got {qb_penalty}"
assert other_team_penalty == 0.0, f"FAIL: a different-team WR should get no stack penalty, got {other_team_penalty}"
print("PASS: same-team stack penalty correctly ranks WR+WR > WR+TE > 0, and never penalizes RB pairings or QB stacks.")
