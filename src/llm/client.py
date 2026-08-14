import json
import os

from google import genai
from google.genai import types
from pydantic import BaseModel, field_validator

from src.engine.draft_math import POSITIONAL_TARGET

MODEL_NAME = "gemini-3.6-flash"

# Gemini latency is observed to be highly variable (as low as ~1s, as high
# as 20-25s+ on the exact same prompt) -- with a 30s pick clock, an
# unbounded call can eat the entire window. 10000ms is the API's own
# enforced minimum deadline; anything slower than that fails fast into
# fallback_recommendation() instead of blocking the whole poll loop.
REQUEST_TIMEOUT_MS = 10000

# Recommendation source labels -- surfaced in the terminal UI so it's always
# obvious whether a pick was synthesized by Gemini or just re-sorted locally.
SOURCE_GEMINI = "gemini"
SOURCE_FALLBACK = "fallback"


class DraftRecommendation(BaseModel):
    recommended_player: str
    alternatives: list[str]
    short_reason: str

    @field_validator("short_reason")
    @classmethod
    def enforce_word_limit(cls, value: str) -> str:
        word_count = len(value.split())
        if word_count > 15:
            raise ValueError(f"short_reason must be 15 words or less, got {word_count}")
        return value


def _build_payload(pareto_candidates: list, roster, draft_metadata: dict) -> dict:
    """Full state awareness (roster, hard caps, draft context) alongside the
    6-8 Pareto-optimal candidates -- each carrying its own quantitative
    signals (RARC, win-probability delta, ceiling delta, survival
    probability, reach penalty) -- so Gemini sees the real shape of the
    decision instead of a single blended score deciding everything upstream.
    """
    return {
        "draft_metadata": draft_metadata,
        "current_roster": roster.slots,
        "positional_counts": roster.position_counts,
        "hard_position_caps": dict(POSITIONAL_TARGET),
        "pareto_candidate_stream": pareto_candidates,
    }


def generate_recommendation(
    archetypal_candidates: list, roster, draft_metadata: dict, clock_seconds: int = 30
) -> DraftRecommendation:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    payload = _build_payload(archetypal_candidates, roster, draft_metadata)
    prompt = (
        "You are a fantasy football draft strategist operating an automated "
        f"decision engine for a high-stakes 12-team Full PPR snake draft. You "
        f"have {clock_seconds} seconds on the clock.\n\n"
        "Below is the current draft state as JSON: your roster, hard "
        "position caps already enforced upstream (never suggest violating "
        "one), and a Pareto-optimal candidate stream (NOT a plain top-N "
        "list -- players who are non-dominated on value vs. ceiling upside, "
        "so weigh each one's own signals rather than assuming rank order "
        "reflects quality). Each candidate carries:\n"
        "- rarc_score: Risk-Adjusted Replacement Cost -- projected value, minus a "
        "variance penalty, minus the expected value of the best player you "
        "could still get at this position by your next turn. Higher means "
        "more urgent to take now rather than wait.\n"
        "- delta_win_prob_pct / delta_ceiling_pts: this player's marginal "
        "contribution to your starting lineup's weekly win probability and "
        "85th-percentile ceiling if drafted now (zero if they'd only sit on "
        "the bench -- e.g. a redundant 2nd TE).\n"
        "- p_avail_next_turn_pct: chance this exact player survives to your "
        "next pick, conditioned on real opponent roster needs.\n"
        "- reach_penalty / composite_score: reach_penalty only fires for a "
        "genuine reach (drafting well before consensus ADP); a high positive "
        "RARC and win-probability contribution can still justify an "
        "aggressive pick despite it -- an elite player who has fallen well "
        "past ADP is a market inefficiency to capture, not something to "
        "avoid.\n"
        "- strategic_profile: a short human-readable tag (e.g. 'Dead Zone "
        "Volume RB', 'Market Fall', 'High Ceiling') for context.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Pick EXACTLY ONE winning player, strictly from the candidates "
        "provided -- never invent or substitute a player not in this list. "
        "List the remaining candidates as alternatives, and give a reason "
        "grounded in the quantitative signals above (e.g. cite RARC, "
        "win-prob delta, or a market-fall opportunity). HARD LIMIT: the "
        "reason must be 12 words or fewer -- count your words before "
        "answering. Terser is better; do not pad it out."
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DraftRecommendation,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        ),
    )

    return DraftRecommendation.model_validate_json(response.text)


def fallback_recommendation(pareto_candidates: list) -> DraftRecommendation:
    """Picks the top-composite-score candidate locally, instantly. Finds the
    max explicitly rather than trusting `pareto_candidates[0]` -- the stream
    IS built best-first, but this is the safety-net path that runs when
    something upstream has already gone wrong (Gemini failure/timeout), so
    it shouldn't also silently assume an ordering invariant it doesn't
    control.
    """
    best = max(pareto_candidates, key=lambda c: c["composite_score"])
    return DraftRecommendation(
        recommended_player=best["player_name"],
        alternatives=[
            candidate["player_name"]
            for candidate in pareto_candidates
            if candidate["player_name"] != best["player_name"]
        ],
        short_reason="Fallback: top composite-score candidate (AI recommendation unavailable).",
    )
