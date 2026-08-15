# anything-but-last

**An AI fantasy football draft copilot that watches a live Sleeper draft in real time and tells you who to take — backed by a real probabilistic value model, not an LLM guessing at rankings.**

Just want to run it? See **[GETTING_STARTED.md](GETTING_STARTED.md)**.

## The problem

Fantasy draft "AI helpers" usually mean one of two things: a static pre-ranked cheat sheet, or an LLM asked to rank 300 players from memory. Neither reacts to the actual draft in front of you — who's gone, who's about to be gone, what your roster actually needs, what your opponents are about to do.

This project is an attempt at the real version of that: a system that recomputes every player's value from scratch after every single pick, using the live draft state, and only hands an LLM the small, already-diverse shortlist it needs a human-language reason for — while staying fast enough to matter under a 30-second pick clock.

## Highlights

- **Two-tier architecture built around a hard latency budget.** All valuation math runs in plain Python/pandas (~10-50ms). The LLM call is capped at a 10-second timeout with an instant local fallback, so a slow or failed API call never costs you the pick.
- **A probabilistic replacement-value model (RARC), not a static ranking.** Every player's score accounts for the live probability they survive to your next turn — itself conditioned on real opponent roster needs pulled from the live draft, not an independence assumption.
- **A real lineup optimizer, not a slot-order assumption.** Every candidate is evaluated against your *actual best possible* starting lineup (re-solved from scratch each time), not whatever slot your draft order happened to assign.
- **A Pareto-optimal candidate stream**, not a single blended ranking — the shortlist handed to the LLM is explicitly diverse on value vs. upside, so the model is never trapped picking between near-clones.
- **Roster-conditioned correlation modeling**, not just per-player scoring — the engine penalizes drafting redundant same-team pass-catchers (real target competition), calibrated against actual fantasy analysis rather than guessed constants, and specifically does *not* penalize the pairings that research showed aren't a real risk.
- **Three interchangeable data sources, swappable live.** The scoring engine is duplicated (not parameterized) across RotoBaller/DraftSharks/FantasyPros-backed variants that all satisfy the same three-function interface, so the running app dispatches to whichever one's selected via a plain dict lookup — no restart, no code edit. Each variant makes a different real tradeoff (heuristic vs. real floor/ceiling variance; ADP vs. expert-consensus rank as the survival-probability input).
- **Debugged like production code.** Several non-obvious correctness bugs were found and fixed through targeted numerical verification against closed-form solutions — see [Engineering notes](#engineering-notes) below.

## Tech stack

Python · pandas · FastAPI · vanilla JS (no frontend framework) · Google Gemini (`google-genai`) · Sleeper's public REST API

No LangChain, no agent framework, no database. Deliberately — see [why](#why-no-agent-framework) below.

## How it works

```text
Sleeper API  →  Roster / Draft State  →  Math Engine (RARC)  →  Gemini  →  Web UI
```

1. A background thread polls Sleeper for new picks every second, so a fresh pick is never missed right before your turn — Sleeper's own endpoint only actually refreshes server-side every ~15-20s regardless of client poll rate, so this is about catching the moment it lands, not squeezing fresher data out of Sleeper.
2. Every undrafted player is scored by a deterministic engine: projected value, minus a variance penalty, minus the expected value of the best player you could still get at that position next turn — all conditioned on live survival probabilities, not static rankings.
3. The top candidates are filtered down to a Pareto-optimal, positionally-diverse shortlist of 6-8 players.
4. That shortlist — never the full player pool — goes to Gemini, which picks one and gives a short, numbers-grounded reason.
5. If Gemini is slow or down, the app instantly falls back to its own top-scored candidate. The draft never stalls.

## Engineering notes

A few decisions and bugs worth calling out, since they're the actual interesting parts of this project:

**Why the LLM never sees the full player pool.** Early iterations gave the LLM 3 fixed "archetype" candidates and later a larger pool; both had failure modes — too few candidates trapped the model between near-identical options, too many recreated the original latency problem. The current design (a Pareto-frontier-filtered shortlist) is a middle ground: small enough to reason over in one call, diverse enough that the model isn't choosing between clones.

**A subtle probability bug that silently distorted every early-round recommendation.** The survival-probability model computed, for each future pick, the *unconditioned* chance a player gets taken there — which looks reasonable in isolation but silently overestimated survival for any player whose ADP fell before the current pick (a case that should be almost impossible to survive). The fix: convert to a properly conditioned hazard rate (probability of being taken now, *given* survival to now), verified numerically against the closed-form solution until they matched exactly.

**A sort-order bug in the exact code path meant to be the safety net.** The local fallback (used when the LLM call fails) assumed the candidate list was sorted best-first. It wasn't — a separate "always include at least one defense/backup RB for roster completeness" rule inserted picks at the front regardless of their actual score. Found via a full recompute-and-diff sanity check, not a passing test suite — the existing tests all still passed, because none of them checked the *default's* correctness.

**Letting research correct an assumption instead of just implementing it.** Asked to add a penalty for drafting redundant skill-position players from the same NFL team, the natural intuition was that *any* same-team pairing (WR+WR, WR+TE, WR+RB, RB+TE) deserved some penalty, just of varying size. Pulling real fantasy analysis before writing the constants surfaced a meaningful correction: WR+WR and WR+TE genuinely compete for a finite, shrinking target pool, but RB production is driven by rushing/goal-line volume — largely orthogonal to passing-game targets — so RB pairings aren't a real competition risk and shipped with zero penalty instead of a smaller one. Guessing plausible-sounding numbers for all four would have been easy and wrong for two of them.

**Swapping a synthetic proxy for real data without silently double-counting.** The default engine has no real per-player variance data, so it estimates one heuristically. A second data source (DraftSharks) publishes actual floor/ceiling projections per player — a strictly better variance signal, but only if it *replaces* the heuristic rather than stacking on top of it (stacking would double-count the same uncertainty). Rather than touch the production engine's already-tuned behavior, the swap shipped as a parallel, independently-tested engine sharing every other component (RARC, survival probability, portfolio optimizer, Pareto frontier) — isolating the one real change instead of risking a regression in a system that already works. Not every new column from the second source made the cut either: strength-of-schedule was left out on purpose, since it's almost certainly already reflected in the base projection, and layering it in separately would double-count the same effect a second time.

**Polling speed is bounded by the data source, not the client.** The obvious lever for "feels more real-time" is polling faster. But Sleeper's own `/picks` endpoint was observed to only refresh server-side every ~15-20s no matter how fast it's polled — so polling speed has no effect on data freshness past a point; it only affects how quickly a pick that already landed gets noticed. An adaptive interval (poll fast only when close to your own turn) was tried first and reverted — it added complexity without a real payoff over a flat 1s interval, given the ceiling above is set by Sleeper either way.

**A logging bug that only exists because of a specific startup ordering.** The app's log file (`draft.log`) was silently empty in production despite `logging.basicConfig()` running correctly at import time. The cause: `uvicorn.run()` calls `logging.config.dictConfig()` internally during its own startup, and the stdlib's `dictConfig` unconditionally closes *every* previously-installed logging handler via an internal `_clearExistingHandlers()` call — regardless of the `disable_existing_loggers` flag, which only governs logger objects, not handlers. So the app's file handler was being torn down the instant the server actually started, before it ever got used. Root-caused by reading CPython's own `logging/config.py` source rather than guessing, then fixed by moving the logging setup to fire from the app's own startup event — which runs *after* uvicorn's internal config, not before it.

**A public JSON API hiding behind a page that looked login-gated.** One data source's projections initially appeared to require a logged-in session (the rendered page only showed 10 rows anonymously). Rather than build a cookie-paste flow, inspecting the page's own network traffic turned up the actual backing REST API it calls client-side — which returns full data with no session cookie at all, just a static app-level API key. Shipped the simpler, credential-free version; the cookie-based implementation was built, tested, and then deleted once the better path was found.

## Why no agent framework

The project's binding constraint is a 30-second real-time clock. Agentic loops, multi-step tool chaining, and heavy framework overhead all trade latency for flexibility this use case can't afford — the LLM's entire job is one JSON-in, JSON-out call at the very end of an already-fast pipeline, not a decision-maker with tool access.

## Project layout

```text
src/
  api/       Sleeper REST wrapper + offline projections refresh
  engine/    draft-turn math, roster tracking, the scoring engine
  llm/       Gemini call, prompt, and local fallback
  ui/        FastAPI server + single-page dashboard
data/        static player projections (CSV)
```

See [GETTING_STARTED.md](GETTING_STARTED.md) for setup, usage, and a plainer-language walkthrough of the math.

## Future improvements

Ideas that would extend this past a single draft-day tool, not yet built:

- **Multi-team trade finder.** Finding a 1-for-1 trade is easy; finding a 3-team trade where every side's projected value goes up is not something a human can compute by hand. Model league rosters as a graph and run a matching/max-flow algorithm to surface those paths automatically.
- **Monte Carlo matchup simulator.** A standard "you're projected to win 112-108" hides the difference between a high-floor player and a boom/bust one with the same average. Sampling each player's score from a distribution (mean + variance, both already computed per player by the draft engine) across thousands of simulated matchups turns that into a real win-probability estimate instead of a single number.
- **Event-driven waiver-wire alerts.** The fantasy manager who claims an injured starter's backup first, before anyone else even sees the news, usually wins that waiver. A background service polling Sleeper's trending-adds endpoint plus injury news, cross-referenced against a league's actual waiver wire, could push that alert automatically.
