# Getting Started

## What is this?

A local web app that watches your live Sleeper fantasy football draft and recommends who to pick, in real time, as the draft happens. You open a page, connect it to your draft, and it updates itself every couple seconds with fresh advice as picks come in.

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

# 2. Add your Gemini API key (optional but recommended)
export GEMINI_API_KEY=your_key_here

# 3. Run it
.venv/bin/python -m src.ui.server
```

Then open **<http://localhost:8000>** in your browser.

## Using it

1. Paste your **Sleeper draft ID** into the input box (see below for how to find it).
2. Enter **your draft slot** — which pick position you are in the draft order (1st, 2nd, 3rd, etc.).
3. Click **Connect Draft**.

From there, the page updates itself automatically. You'll see:

- Whether you're currently on the clock, and how many picks until your turn.
- A shortlist of the best available players right now, each with a short explanation of why it's a strong option.
- Your roster filling up live, slot by slot, as you and others draft — each player shown alongside the round.pick number they were actually drafted at (e.g. `1.01`).
- A running feed of recent picks.

You can connect to a different draft at any time — just enter a new draft ID and click Connect again, no need to restart anything.

### Finding your draft ID

Open your draft in Sleeper (web or app) and look at the URL — the draft ID is the long number in it, e.g. `sleeper.com/draft/nfl/1234567890123456789`. That whole number is what you paste in.

### If you skip the API key

The app still works completely without `GEMINI_API_KEY` set — it just always uses its own local top-ranked pick instead of an AI-written recommendation. You'll see "Fallback" instead of "Gemini" as the source of each pick. Everything else (the live scoring, the roster tracking, the draft-board updates) works identically either way.

## How it decides who to recommend, in plain terms

For every player still on the board, the app asks two main questions:

**"Is this player actually worth taking right now, or could I probably still get someone just as good later?"** It estimates the odds each player survives to your next pick — factoring in not just their average draft position, but what the specific teams picking before your next turn still need. A player who's nearly certain to be gone by your next pick scores as more urgent than one who'll probably still be sitting there.

**"Does this player actually make my team better?"** Rather than assuming whatever slot you happened to draft someone into is where they'll stay, it re-solves your entire best possible starting lineup every time, so a strong player correctly gets credit for upgrading your team even if your literal roster page hasn't caught up yet.

It also nudges you away from redundant same-team picks — e.g. drafting a wide receiver who'd be fighting one of your own other receivers for targets on the same NFL team — without ever penalizing pairing a QB with their own teammates, since that's a well-known *good* strategy, not a risk.

Those two signals (plus that same-team check) get combined into one score per player, the strongest and most varied options get shortlisted, and — if you've set up an API key — Gemini reads that shortlist and writes the actual recommendation you see, in one sentence, grounded in those same numbers. If it's ever too slow to respond in time, the app just uses its own top-scored pick instead, instantly, so you're never left waiting past your turn.

## Troubleshooting

**"Could not fetch draft from Sleeper"** — double check the draft ID. Mock draft IDs on Sleeper can expire or reset; if one stops working mid-session, start a fresh mock draft and use its new ID.

**The draft looks frozen / picks aren't updating** — check `draft.log` in the project folder for errors. The app automatically recovers from most transient hiccups within a few seconds on its own.

**No recommendations showing up** — recommendations only appear once you're on the clock. Before that, you'll still see the live shortlist of top available players, just without a specific pick called out.

## For developers

Manual regression scripts (not pytest — run directly):

```bash
.venv/bin/python test_draft_math.py         # scoring engine rules, in isolation
.venv/bin/python test_draft_simulation.py   # full simulated 15-round draft
.venv/bin/python test_llm.py                # real call to Gemini (needs GEMINI_API_KEY)
.venv/bin/python test_api.py <draft_id>      # sanity-checks the Sleeper API wrapper
```

Run the first three after changing anything under `src/engine/` or `src/llm/`. Refresh player projections offline with `.venv/bin/python -m src.api.update_data` before a draft (this is not run automatically and does not happen live).

For the full technical writeup of how the scoring engine works, see the [README](README.md#engineering-notes) and the comments in `src/engine/draft_math.py`.
