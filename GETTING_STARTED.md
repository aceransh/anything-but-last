# Getting Started

## What is this?

A local web app that watches your live Sleeper fantasy football draft and recommends who to pick, in real time, as the draft happens. You open a page, connect it to your draft, and it updates itself automatically with fresh advice as picks come in — checking for new picks every second.

It's not a static cheat sheet — it recalculates its recommendations after every single pick, accounting for who's gone, what your roster still needs, and how likely each remaining player is to still be available the next time it's your turn.

## Prerequisites

- Python 3.11+
- A free [Google AI Studio](https://aistudio.google.com) API key (optional — the app works without one, just without AI-written explanations; see [If you skip the API key](#if-you-skip-the-api-key))
- A Sleeper draft ID (see [Finding your draft ID](#finding-your-draft-id))

## Quick start

```bash
# 1. Set up a virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 2. Add your Gemini API key (optional but recommended) -- either
# export it directly, or copy .env.example to .env and fill it in there
export GEMINI_API_KEY=your_key_here

# 3. Run it
.venv/bin/python -m src.ui.server
```

Then open **<http://localhost:8000>** in your browser.

## Using it

1. Paste your **Sleeper draft ID** into the input box (see below for how to find it).
2. Enter **your draft slot** — which pick position you are in the draft order (1st, 2nd, 3rd, etc.).
3. Pick a **data source** — RotoBaller, DraftSharks, FantasyPros, Sleeper, or Hybrid (see [Data sources](#data-sources) below for what's different between them).
4. Click **Connect Draft**.

From there, the page updates itself automatically. You'll see:

- Whether you're currently on the clock, and how many picks until your turn.
- A shortlist of the best available players right now, each with a short explanation of why it's a strong option.
- Your roster filling up live, slot by slot, as you and others draft — each player shown alongside the round.pick number they were actually drafted at (e.g. `1.01`).
- A running feed of recent picks.

You can connect to a different draft, slot, or data source at any time — just change the fields and click Connect again, no need to restart anything.

### Finding your draft ID

Open your draft in Sleeper (web or app) and look at the URL — the draft ID is the long number in it, e.g. `sleeper.com/draft/nfl/1234567890123456789`. That whole number is what you paste in.

### If you skip the API key

The app still works completely without `GEMINI_API_KEY` set — it just always uses its own local top-ranked pick instead of an AI-written recommendation. You'll see "Fallback" instead of "Gemini" as the source of each pick. Everything else (the live scoring, the roster tracking, the draft-board updates) works identically either way.

## How it decides who to recommend, in plain terms

For every player still on the board, the app asks two main questions:

**"Is this player actually worth taking right now, or could I probably still get someone just as good later?"** It estimates the odds each player survives to your next pick — factoring in not just their average draft position, but what the specific teams picking before your next turn still need, *and* how many real alternatives are actually left at that position. A team needing a running back when only two decent ones remain is treated as a much bigger threat to that player's survival than the same need against a deep, healthy position group — not just "someone needs it" as a flat risk regardless of scarcity.

**"Does this player actually make my team better?"** Rather than assuming whatever slot you happened to draft someone into is where they'll stay, it re-solves your entire best possible starting lineup every time, so a strong player correctly gets credit for upgrading your team even if your literal roster page hasn't caught up yet.

**"Is this risk actually a downside, or is it just upside I shouldn't be punishing?"** A player's bust risk and breakout upside used to be scored as the same thing — a wider range of outcomes, in either direction, counted equally against them. That's backwards: a player whose *ceiling* is enormous shouldn't be penalized as if that were bust risk. Risk is now scored from the downside distance alone, so a bigger ceiling no longer costs a player anything on that front — it just shows up correctly as upside instead.

It also nudges you away from redundant same-team picks — e.g. drafting a wide receiver who'd be fighting one of your own other receivers for targets on the same NFL team — without ever penalizing pairing a QB with their own teammates, since that's a well-known *good* strategy, not a risk.

There's one deliberate exception to the app's own roster rules: once you've locked in a clear starting QB early, it normally won't suggest a second one for the rest of the draft — that roster slot is basically full value already. But the lock isn't absolute. If a QB's value falls so far outside normal range that skipping them would clearly cost you more than the backup-QB slot itself, the app will still surface them — the same "a market inefficiency is something to capture, not avoid" philosophy that governs a plain market-fall on any other player.

Those signals (plus the same-team check) get combined into one score per player, the strongest and most varied options get shortlisted, and — if you've set up an API key — Gemini reads that shortlist and writes the actual recommendation you see, in one sentence, grounded in those same numbers. If it's ever too slow to respond in time, the app just uses its own top-scored pick instead, instantly, so you're never left waiting past your turn.

## Data sources

The app scores players using a local CSV file, not a live API call — that's deliberate, it's what keeps recommendations instant during your pick. There are five interchangeable sources, picked from the dropdown next to the draft ID field:

- **RotoBaller** (`data/projections_rb.csv`) — the default/original source.
- **DraftSharks** (`data/projections_ds.csv`) — publishes real floor/ceiling projections per player, used here as an actual measured risk signal instead of an estimated one.
- **FantasyPros** (`data/projections_fp.csv`) — real cross-platform Average Draft Position (blended from ESPN, CBS, RTSports, Fantrax, and Sleeper's own live drafts, not just human-analyst opinion) plus PPR projections. This is the only single source with a second, separate signal: when FantasyPros' own expert consensus rank thinks a player is meaningfully better than where the market is actually drafting them, you'll see an **"Expert Buy-Low"** tag on that candidate.
- **Sleeper** (`data/projections_sl.csv`) — pulled directly from Sleeper's own projections/ADP endpoint, the same platform your draft is actually happening on. Its ADP reflects exactly the room you're drafting in, not a third-party estimate of it.
- **Hybrid** (`data/projections_hybrid.csv`) — a local merge of all four other sources, not just an average of them. It blends projections and risk data across whichever sources have a given player, but deliberately keeps ADP as *two separate numbers* instead of one: Sleeper's own ADP drives how likely opponents are to take a player before your next turn (since that's the room you're actually in), while FantasyPros' real cross-platform ADP drives whether a pick counts as a genuine reach and powers the same "Expert Buy-Low" tag as the FantasyPros source above. Refresh the other four first — this one doesn't hit the network itself, it just re-merges whatever's already on disk.

Whichever CSV you're using only knows what was in it the last time it was refreshed. Before a draft, refresh whichever source you plan to use — either from the app itself (click **Refresh \<Source\> Data**, which appears next to the data-source dropdown once you've picked one) or from the command line:

```bash
.venv/bin/python -m src.api.update_data_rotoballer    # RotoBaller
.venv/bin/python -m src.api.update_data_draftsharks   # DraftSharks
.venv/bin/python -m src.api.update_data_fantasypros   # FantasyPros
.venv/bin/python -m src.api.update_data_sl            # Sleeper
.venv/bin/python -m src.api.update_data_hybrid        # Hybrid (run after refreshing the other four)
```

None of these need a login or an API key you have to set up yourself — refreshing is a single command (or button click) either way. Refreshing isn't automatic — run it whenever rankings feel stale, ideally right before each draft.

## Troubleshooting

**"Could not fetch draft from Sleeper"** — double check the draft ID. Mock draft IDs on Sleeper can expire or reset; if one stops working mid-session, start a fresh mock draft and use its new ID.

**The draft looks frozen / picks aren't updating** — check `draft.log` in the project folder for errors. The app automatically recovers from most transient hiccups within a few seconds on its own.

**No recommendations showing up** — recommendations only appear once you're on the clock. Before that, you'll still see the live shortlist of top available players, just without a specific pick called out.

## For developers

Manual regression scripts (not pytest — run directly):

```bash
.venv/bin/python test_draft_math.py            # scoring engine rules (RotoBaller), in isolation
.venv/bin/python test_draft_simulation.py      # full simulated 15-round draft (RotoBaller)
.venv/bin/python test_draft_math_ds.py         # same rules, DraftSharks variant
.venv/bin/python test_draft_simulation_ds.py   # same simulation, DraftSharks variant
.venv/bin/python test_draft_math_fp.py         # same rules, FantasyPros variant
.venv/bin/python test_draft_simulation_fp.py   # same simulation, FantasyPros variant
.venv/bin/python test_draft_math_sl.py         # same rules, Sleeper variant
.venv/bin/python test_draft_simulation_sl.py   # same simulation, Sleeper variant
.venv/bin/python test_draft_math_hybrid.py     # same rules, Hybrid variant
.venv/bin/python test_draft_simulation_hybrid.py  # same simulation, Hybrid variant
.venv/bin/python test_llm.py                   # real call to Gemini (needs GEMINI_API_KEY)
.venv/bin/python test_api.py <draft_id>         # sanity-checks the Sleeper API wrapper
```

Run the math/simulation pair for whichever engine(s) you touched. `compare_draft_engines.py` (also run directly, no args) is a non-pass/fail report — runs all five engines' independent 15-round simulations and prints how differently they draft, not a regression gate. See [Data sources](#data-sources) above for refreshing each engine's CSV.

For the full technical writeup of how the scoring engine works, see the [README](README.md#engineering-notes) and the comments in `src/engine/draft_math_rb.py`.
