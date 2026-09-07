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
- **Five interchangeable data sources, swappable live — one of them synthesized from the other four.** The scoring engine is duplicated (not parameterized) across RotoBaller/DraftSharks/FantasyPros/Sleeper-backed variants that all satisfy the same three-function interface, plus a fifth "Hybrid" source that locally merges the other four instead of fetching from anywhere new. The running app dispatches to whichever one's selected via a plain dict lookup — no restart, no code edit. Each single source makes a different real tradeoff (heuristic vs. real floor/ceiling variance; platform-native ADP vs. cross-platform consensus; deepest player pool vs. richest per-player signal); the Hybrid variant doesn't just average them together — it splits *which* ADP feed answers *which* question, using the platform you're actually drafting on to model opponent behavior and a genuine cross-platform consensus to judge whether a pick is a real market reach, since those are different questions with different right answers.
- **Debugged like production code.** Several non-obvious correctness bugs were found and fixed through targeted numerical verification against closed-form solutions — see [Engineering notes](#engineering-notes) below.

## Tech stack

Python · pandas · FastAPI · vanilla JS (no frontend framework) · Google Gemini (`google-genai`) · Sleeper's public REST API

No LangChain, no agent framework, no database. Deliberately — see [why](#why-no-agent-framework) below.

A second, separate app for in-season features (not draft day) is deployed alongside this one — see [Season tools](#season-tools) below for that stack.

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

**The same trap, a second time — plus a subtler mistake hiding right behind it.** Real per-platform Average Draft Position from the same provider was initially written off as needing a login, based on one gated report page. A different page on the same site — "Real-Time ADP" — turned out to be fully public, and the obvious move was to call the same rankings API already in use, filtered down to just the fantasy platforms instead of human analysts. That produced real-looking numbers that were quietly wrong: one of the three platforms wasn't actually returning any data for most players, so the "three-platform average" was silently just two platforms. It only surfaced by checking the computed numbers against what the live page actually displayed and finding they didn't match. Tracing the page's own minified JS bundle further showed why: the number on screen comes from a second, entirely separate API call on a different host, blending five platforms with real recency-weighting — not the endpoint that seemed like the obvious answer at all.

**A "guarantee" that only guaranteed inclusion, not the pick.** Two roster slots (kicker, defense) were "guaranteed" a draft pick before the draft ended, via a rule that added them to the candidate pool late and trusted the scoring model to naturally pick them. It always had a hidden failure mode: the win-probability model deliberately ignores those two positions entirely (their week-to-week output is treated as noise when comparing team strength), so neither ever earns real credit for filling its own mandatory slot — leaving a lone "guaranteed" candidate to survive purely on raw projected points against genuine bench depth. A data refresh eventually shifted that race enough to actually lose it, and a full simulated draft ended with no kicker at all. Root-caused to the actual mechanism (not just patched at the symptom) and fixed by hardening the requirement itself for the round(s) it matters, rather than recalibrating a win-probability model that's correctly tuned for every other position.

**Reusing a dedup rule built for a different problem entirely.** Merging independent data providers into one player pool hit real name mismatches no punctuation/suffix normalization catches — the same real player spelled "Cam" on one source and "Cameron" on another, producing two rows for one person. The fix wasn't a hardcoded nickname table; it was the exact same rule already built for a different job (matching a live draft's pick names against the projections sheet): treat two spellings as the same player whenever they share a last name that's unambiguous within each individual source. One small piece of matching logic, reused for a problem it was never written for.

**Two different ADP questions were being answered with one number.** A later revision of the Hybrid source, based on external research, argued that blending multiple data feeds into a single ADP figure was a structural error, not just an accuracy tradeoff: predicting whether a specific opponent will take a player *in this specific Sleeper draft room* is a different question from judging whether a pick is a genuine market reach, and the two need different inputs — the platform you're actually drafting on for the first, real cross-platform consensus for the second. Implementing that meant threading two independent ADP values through the survival-probability and reach-penalty math separately, rather than one. The research itself wasn't taken at face value, either: its proposed "Expert Buy-Low" formula, read literally, computed the *opposite* of what its own explanation described — confirmed by rederiving the direction from the plain-English definition and cross-checking against an already-shipped, already-correct version of the same signal elsewhere in the codebase, and following the actual math and the working precedent instead of the paper's own equation.

**A downside-only risk fix that silently broke a working feature two layers away.** A player's variance penalty was originally computed from a real floor-to-ceiling spread, but that meant a bigger ceiling — pure upside — increased the same risk penalty as a bigger bust risk, which is backwards for a risk-adjusted score. Rederiving variance from the downside distance alone fixed that correctly. It also collapsed a separate, already-working feature to zero: a late-round "handcuff" RB quota that specifically hunts for exactly the boom/bust profile the fix just stopped measuring (real backup-RB data is heavily skewed — a near-zero floor, since a bench role means you barely score at all, against a huge ceiling if the starter gets hurt). The floor-only fix was correct; the feature that depended on the full spread wasn't warned about the change. Found by rerunning the existing regression suite rather than assuming the fix was isolated, and fixed by pointing the quota's detector at the real ceiling ratio directly instead of a derived stand-in for it.

**Turning down a fix that was bigger than it looked.** A proposal to replace the survival-probability model's opponent-demand heuristic with a Monte Carlo simulation — sampling hundreds of simulated draft sequences per pick instead of a closed-form estimate — would have captured a real gap (today's model can't see "three teams need a running back and only two are left," a genuine draft dynamic). It was scoped down instead of built: a real rollout engine needs a full joint pick-by-pick simulator, a materially bigger addition than presented, and it introduces something the current deterministic model doesn't have at all — run-to-run randomness, which would make recommendations visibly flicker between identical consecutive polls of an unchanged board. Shipped a smaller, fully deterministic version that captures the same core signal (scale the existing demand boost by how thin the remaining position actually is) instead, calibrated so it's mathematically identical to the old behavior at typical depth and only diverges when a position is genuinely thin.

**Duplication that was the right call, until it wasn't.** Each new data-source variant had originally been built as a full, independent copy of the scoring engine — a deliberate choice: no shared abstraction meant no risk of one source's fix silently breaking another. That stopped being free the moment a fix needed to land in four near-identical ~1000-line files at once, which happened three times in a single session. Rather than parameterize preemptively at the start (when only one variant existed and the "right" abstraction boundary wasn't yet knowable), the duplication was left alone until the actual pain showed up — then collapsed into one shared module with each source supplying only its real differences as explicit function arguments, never a closure or a monkeypatched global. One source that outgrew a simple parameter swap (a dual-track ADP model touching several call sites at once) was deliberately left out of the consolidation rather than forced to fit — verified as a pure reorganization, not a behavior change, by rerunning the full existing regression suite (every rule, every simulated draft, the cross-engine comparison) and confirming byte-identical output before and after.

**A platform's own "fix" broke every route identically, in a way that looked like the app's own bug.** Deploying the season-tools backend (below) to Vercel, a manual rewrite rule sending every request path to one function 404'd every route — including the framework's own auto-generated `/docs` endpoint, which meant it couldn't be a routing typo in this app's own code. The actual cause was on the platform side: Vercel's build log itself warned that rewrite destinations are now passed to backend functions as the literal request path, not just used to pick which function handles a request — a recent, documented behavior change that inverted what the rewrite used to do. The fix was deleting the rewrite entirely; the platform's own zero-config framework detection already routed everything correctly without it. Read the build log before assuming a 404 is your own code.

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

backend/     season-tools API (FastAPI, deployed to Vercel)
frontend/    season-tools web app (React + TypeScript, deployed to Vercel)
supabase/    season-tools schema migrations
```

See [GETTING_STARTED.md](GETTING_STARTED.md) for setup, usage, and a plainer-language walkthrough of the math.

## Season tools

The draft copilot above covers exactly one day of the fantasy season. A second, separate, deployed web app is the start of covering the other ~17 weeks — currently just the foundation (auth, database, hosting), no season-long features yet. React + TypeScript frontend, FastAPI backend, Supabase (Postgres + Auth), both halves deployed on Vercel. Live: sign up, connect a Sleeper league by ID, see it on a dashboard — the minimum real slice proving the whole chain works before any actual fantasy-management logic gets built on top of it.

It's a deliberately separate app from the draft copilot, not an extension of it — the draft tool's whole architecture (in-memory state, single background thread, no auth, no persistence) is built around a 30-second live pick clock and a single local user; this one needs multi-user auth and a real database, neither of which the draft tool needs or should take on.

## Future improvements

Draft day is covered. Everything below is aimed at the other ~17 weeks, researched and scoped, and now has real infrastructure to build on (see [Season tools](#season-tools) above) — but none of it is built yet. One constraint shapes all of it: Sleeper's API is entirely read-only, so this can only ever be a copilot that tells you exactly what to do — not an autopilot that does it for you.

- **Weekly lineup optimizer.** The most natural next build, and the biggest gap: right now the app goes silent the moment the draft ends. Real per-week player projections turned out to be one parameter change away on a data source already integrated, not a new one to go find — so this reuses the existing lineup-optimizer math almost as-is, just pointed at "who should start this week" instead of "who should I draft."
- **Injury and bye-week warnings.** A lineup check that flags a starter who's actually on a bye or banged up before you lock it in, using the same roster data the optimizer above already needs.
- **Trade evaluator, starting simple.** A 2-team version first — score a proposed trade with the app's existing valuation math — before tackling the harder version below.
- **Multi-team trade finder.** Finding a 1-for-1 trade is easy; finding a 3-team trade where every side's projected value goes up is not something a human can compute by hand. Model league rosters as a graph and run a matching/max-flow algorithm to surface those paths automatically.
- **Season-long playoff-odds tracker.** Simulate the rest of the season, not just the next matchup, to estimate each team's real playoff probability given where the league actually stands.
- **Monte Carlo matchup simulator.** A standard "you're projected to win 112-108" hides the difference between a high-floor player and a boom/bust one with the same average. Sampling each player's score from a distribution (mean + variance, both already computed per player by the draft engine) across thousands of simulated matchups turns that into a real win-probability estimate instead of a single number.
- **Event-driven waiver-wire alerts.** The fantasy manager who claims an injured starter's backup first, before anyone else even sees the news, usually wins that waiver. A background service polling Sleeper's trending-adds endpoint plus injury status, cross-referenced against a league's actual waiver wire, could push that alert automatically.
