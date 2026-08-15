import logging
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from google.genai import errors as genai_errors
from pydantic import BaseModel

from src.api.sleeper import get_draft_picks, get_draft_status
from src.engine.draft_math import detect_roster_archetype, generate_pareto_candidate_stream, get_drafted_names
from src.engine.draft_state import compute_pick_slot, format_pick_alert, picks_until_my_turn
from src.engine.roster import ROSTER_SLOTS, Roster
from src.llm.client import (
    SOURCE_FALLBACK,
    SOURCE_GEMINI,
    fallback_recommendation,
    generate_recommendation,
)

logger = logging.getLogger(__name__)

# Adaptive polling: Sleeper's own /picks endpoint only refreshes server-side
# every ~15-20s regardless of how fast we poll it, so polling faster than
# that never gets fresher data -- it just burns requests. The one place
# polling speed still matters is catching a fresh pick the instant it lands
# right before our turn, so we poll fast only when close to being on the
# clock and slow otherwise.
POLL_INTERVAL_NEAR_SECONDS = 1
POLL_INTERVAL_FAR_SECONDS = 5
NEAR_TURN_PICKS_THRESHOLD = 5  # "close to my turn" = 0-5 picks away, inclusive
PROJECTIONS_CSV = "data/projections.csv"
LOG_FILE = "draft.log"
RECENT_PICKS_MAX = 4
# A single pick-count regression is usually a transient fetch glitch
# (get_draft_picks() returns [] on a request error). But if it persists for
# this many consecutive ticks, that's not transient -- the draft itself
# likely reset/expired -- and resyncing beats freezing forever.
MAX_TRANSIENT_REGRESSION_TICKS = 3
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",  # fresh log each server start, not an unbounded append across dev sessions
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="Fantasy Football Draft Copilot")

_lock = threading.Lock()

# Desired config, set via POST /api/config -- the poll loop watches this and
# reconnects whenever it changes.
_config = {"draft_id": None, "my_draft_slot": 1}

# Snapshot the frontend polls via GET /api/state. Same shape at rest and
# mid-draft so the frontend never has to special-case "not connected yet".
_state = {
    "connected": False,
    "polling": False,
    "error": None,
    "draft_id": None,
    "my_draft_slot": 1,
    "pick_no": None,
    "round_num": None,
    "pick_in_round": None,
    "slot_on_clock": None,
    "teams": None,
    "total_rounds": None,
    "on_the_clock": False,
    "picks_away": None,
    "eta_seconds": None,
    "pick_timer": None,
    "candidates": [],
    "recommendation": None,
    "roster_needs": "Not connected",
    "roster_slots": {position: [] for position in ROSTER_SLOTS},
    "roster_slot_capacity": ROSTER_SLOTS,
    "roster_pick_labels": {},
    "recent_picks": [],
    "draft_complete": False,
}


class ConfigUpdate(BaseModel):
    draft_id: str
    my_draft_slot: int = 1


def _update_state(**kwargs) -> None:
    with _lock:
        _state.update(kwargs)


def _snapshot_state() -> dict:
    with _lock:
        return dict(_state)


def _poll_loop() -> None:
    """Polls Sleeper, runs the RARC/roster/Gemini pipeline, and publishes
    each tick into `_state` for the frontend to read. Re-reads `_config`
    every tick so a POST to /api/config can swap the active draft without
    restarting the process.
    """
    active_draft_id = None
    my_draft_slot = 1
    roster = Roster()
    roster_pick_labels: dict[str, str] = {}
    last_pick_count = -1
    regression_streak = 0
    archetypal_candidates: list = []
    recommendation_cache: dict = {}
    recent_picks: list[str] = []
    teams = total_rounds = pick_timer = total_picks = None

    while True:
        with _lock:
            desired_draft_id = _config["draft_id"]
            desired_slot = _config["my_draft_slot"]

        if desired_draft_id is None:
            time.sleep(POLL_INTERVAL_FAR_SECONDS)
            continue

        if desired_draft_id != active_draft_id or desired_slot != my_draft_slot:
            active_draft_id = desired_draft_id
            my_draft_slot = desired_slot
            roster = Roster()
            roster_pick_labels = {}
            last_pick_count = -1
            regression_streak = 0
            archetypal_candidates = []
            recommendation_cache = {}
            recent_picks = []

            status = get_draft_status(active_draft_id)
            if not status:
                logger.warning("Could not fetch draft status for draft_id=%s", active_draft_id)
                _update_state(
                    connected=False,
                    polling=False,
                    error=f"Could not fetch draft {active_draft_id} from Sleeper.",
                    draft_id=active_draft_id,
                    my_draft_slot=my_draft_slot,
                )
                # Force a retry against the same draft_id on the next tick
                # rather than spinning forever on a stale, already-failed one.
                active_draft_id = None
                time.sleep(POLL_INTERVAL_FAR_SECONDS)
                continue

            settings = status.get("settings", {})
            teams = settings.get("teams", 12)
            total_rounds = settings.get("rounds", 15)
            pick_timer = settings.get("pick_timer", 60)
            total_picks = teams * total_rounds
            _update_state(
                connected=True,
                polling=True,
                error=None,
                draft_id=active_draft_id,
                my_draft_slot=my_draft_slot,
                teams=teams,
                total_rounds=total_rounds,
                pick_timer=pick_timer,
                draft_complete=False,
            )

        tick_start = time.monotonic()
        t0 = time.monotonic()
        picks = get_draft_picks(active_draft_id)
        logger.info("get_draft_picks: %.2fs (%d picks)", time.monotonic() - t0, len(picks))
        pick_count = len(picks)

        if pick_count < last_pick_count:
            regression_streak += 1
            if regression_streak <= MAX_TRANSIENT_REGRESSION_TICKS:
                logger.warning(
                    "Pick count regressed (%s -> %s, streak %d/%d); treating as a "
                    "transient fetch error and skipping this tick.",
                    last_pick_count,
                    pick_count,
                    regression_streak,
                    MAX_TRANSIENT_REGRESSION_TICKS,
                )
                # Proximity to our turn isn't known yet this tick (the fetch
                # itself is what's in question) -- default to the far interval.
                time.sleep(POLL_INTERVAL_FAR_SECONDS)
                continue
            # Regressed for too many ticks in a row to still be a blip -- the
            # draft most likely reset/expired underneath us. Resync to the
            # new reality instead of freezing here forever.
            logger.warning(
                "Pick count regressed (%s -> %s) for %d consecutive ticks; draft "
                "likely reset/expired. Resyncing instead of freezing.",
                last_pick_count,
                pick_count,
                regression_streak,
            )
            last_pick_count = -1
            regression_streak = 0
            recent_picks = []
            recommendation_cache = {}
        else:
            regression_streak = 0

        current_pick_no = pick_count + 1
        if current_pick_no > total_picks:
            _update_state(polling=False, draft_complete=True, on_the_clock=False)
            time.sleep(POLL_INTERVAL_FAR_SECONDS)
            continue

        slot_on_clock, round_num, pick_in_round = compute_pick_slot(current_pick_no, teams)
        on_the_clock = slot_on_clock == my_draft_slot
        picks_away = picks_until_my_turn(current_pick_no, my_draft_slot, teams)
        eta_seconds = picks_away * pick_timer
        # RARC's survival/replacement math looks forward to the manager's NEXT
        # turn after this pick is decided, not "0 picks away" when this pick
        # IS that turn.
        picks_until_next_turn = picks_until_my_turn(current_pick_no + 1, my_draft_slot, teams)

        if pick_count != last_pick_count:
            new_picks = picks[max(last_pick_count, 0):pick_count]
            for pick in new_picks:
                alert = format_pick_alert(pick, my_draft_slot)
                if alert:
                    recent_picks.insert(0, alert)
            recent_picks[:] = recent_picks[:RECENT_PICKS_MAX]

            roster = Roster()
            roster_pick_labels = {}
            for pick in picks:
                if pick.get("draft_slot") == my_draft_slot and pick.get("metadata"):
                    _, pick_round, pick_slot_in_round = compute_pick_slot(pick["pick_no"], teams)
                    player_name = f"{pick['metadata']['first_name']} {pick['metadata']['last_name']}"
                    roster.add_player(
                        player_name,
                        pick["metadata"].get("position", "BN"),
                        round_num=pick_round,
                    )
                    roster_pick_labels[player_name] = f"{pick_round}.{pick_slot_in_round:02d}"

            drafted_names = get_drafted_names(picks)
            t0 = time.monotonic()
            archetypal_candidates = generate_pareto_candidate_stream(
                drafted_names,
                PROJECTIONS_CSV,
                roster=roster,
                round_num=round_num,
                total_rounds=total_rounds,
                current_pick_no=current_pick_no,
                picks_until_next_turn=picks_until_next_turn,
                picks=picks,
                teams=teams,
            )
            logger.info("generate_pareto_candidate_stream: %.2fs", time.monotonic() - t0)

            for stale_pick_no in [p for p in recommendation_cache if p < current_pick_no]:
                del recommendation_cache[stale_pick_no]

            last_pick_count = pick_count

        recommendation = None
        recommendation_source = None
        if on_the_clock and archetypal_candidates:
            available_names = {candidate["player_name"] for candidate in archetypal_candidates}
            cached = recommendation_cache.get(current_pick_no)
            if cached is not None and cached[0].recommended_player in available_names:
                recommendation, recommendation_source = cached
            else:
                draft_metadata = {
                    "current_round": round_num,
                    "pick_number": current_pick_no,
                    "picks_until_next_turn": picks_until_next_turn,
                    "roster_archetype_detected": detect_roster_archetype(roster, round_num),
                }
                t0 = time.monotonic()
                try:
                    recommendation = generate_recommendation(
                        archetypal_candidates, roster, draft_metadata
                    )
                    recommendation_source = SOURCE_GEMINI
                    logger.info(
                        "generate_recommendation: %.2fs (pick %s)",
                        time.monotonic() - t0,
                        current_pick_no,
                    )
                except Exception as exc:
                    reason = (
                        f"HTTP {exc.code}" if isinstance(exc, genai_errors.APIError) else str(exc)
                    )
                    logger.warning(
                        "Gemini recommendation failed for pick %s after %.2fs (%s); "
                        "falling back to top Pure Value candidate.",
                        current_pick_no,
                        time.monotonic() - t0,
                        reason,
                    )
                    recommendation = fallback_recommendation(archetypal_candidates)
                    recommendation_source = SOURCE_FALLBACK
                recommendation_cache[current_pick_no] = (recommendation, recommendation_source)

        rec_payload = None
        if recommendation is not None:
            rec_payload = {
                "recommended_player": recommendation.recommended_player,
                "alternatives": recommendation.alternatives,
                "short_reason": recommendation.short_reason,
                "source": recommendation_source,
            }

        _update_state(
            connected=True,
            polling=True,
            error=None,
            pick_no=current_pick_no,
            round_num=round_num,
            pick_in_round=pick_in_round,
            slot_on_clock=slot_on_clock,
            teams=teams,
            total_rounds=total_rounds,
            on_the_clock=on_the_clock,
            picks_away=picks_away,
            eta_seconds=eta_seconds,
            candidates=list(archetypal_candidates),
            recommendation=rec_payload,
            roster_needs=roster.roster_needs_summary(),
            roster_slots={position: list(players) for position, players in roster.slots.items()},
            roster_pick_labels=dict(roster_pick_labels),
            recent_picks=list(recent_picks),
            draft_complete=False,
        )

        next_sleep_seconds = (
            POLL_INTERVAL_NEAR_SECONDS
            if picks_away <= NEAR_TURN_PICKS_THRESHOLD
            else POLL_INTERVAL_FAR_SECONDS
        )
        logger.info(
            "poll tick for pick #%s: %.2fs total (%s picks away, before %ss sleep)",
            current_pick_no,
            time.monotonic() - tick_start,
            picks_away,
            next_sleep_seconds,
        )
        time.sleep(next_sleep_seconds)


@app.on_event("startup")
def _start_poll_loop() -> None:
    threading.Thread(target=_poll_loop, daemon=True).start()


@app.get("/api/config")
def get_config() -> dict:
    with _lock:
        return dict(_config)


@app.post("/api/config")
def set_config(update: ConfigUpdate) -> dict:
    with _lock:
        _config["draft_id"] = update.draft_id
        _config["my_draft_slot"] = update.my_draft_slot
        _state["error"] = None
    return {"draft_id": update.draft_id, "my_draft_slot": update.my_draft_slot}


@app.get("/api/state")
def get_state() -> dict:
    return _snapshot_state()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return TEMPLATE_PATH.read_text()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
