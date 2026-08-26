import logging
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from google.genai import errors as genai_errors
from pydantic import BaseModel

from src.api import (
    update_data_rotoballer,
    update_data_draftsharks,
    update_data_fantasypros,
    update_data_hybrid,
)
from src.api.sleeper import get_draft_picks, get_draft_status
from src.engine import draft_math_rb, draft_math_ds, draft_math_fp, draft_math_hybrid
from src.engine.draft_state import compute_pick_slot, format_pick_alert, picks_until_my_turn
from src.engine.roster import ROSTER_SLOTS, Roster
from src.llm.client import (
    SOURCE_FALLBACK,
    SOURCE_GEMINI,
    fallback_recommendation,
    generate_recommendation,
)

logger = logging.getLogger(__name__)

# Flat 1s polling. Sleeper's own /picks endpoint only refreshes server-side
# every ~15-20s regardless of how fast we poll it, so this doesn't get
# fresher data on its own -- but the prior near/far adaptive split wasn't
# working well in practice, so this reverts to a simple constant interval.
POLL_INTERVAL_SECONDS = 1
# Runtime-selectable data sources -- all three engine modules export the
# same three functions (get_drafted_names, detect_roster_archetype,
# generate_pareto_candidate_stream) with identical signatures, so swapping
# is a genuine drop-in: {key: (module, csv_path)}. Key is whatever the
# frontend's data-source <select> posts as `data_source`.
DATA_SOURCES = {
    "rotoballer": (draft_math_rb, "data/projections_rb.csv"),
    "draftsharks": (draft_math_ds, "data/projections_ds.csv"),
    "fantasypros": (draft_math_fp, "data/projections_fp.csv"),
    "hybrid": (draft_math_hybrid, "data/projections_hybrid.csv"),
}
DEFAULT_DATA_SOURCE = "fantasypros"
LOG_FILE = "draft.log"
RECENT_PICKS_MAX = 4
# A single pick-count regression is usually a transient fetch glitch
# (get_draft_picks() returns [] on a request error). But if it persists for
# this many consecutive ticks, that's not transient -- the draft itself
# likely reset/expired -- and resyncing beats freezing forever.
MAX_TRANSIENT_REGRESSION_TICKS = 3
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

app = FastAPI(title="Fantasy Football Draft Copilot")

_lock = threading.Lock()

# Desired config, set via POST /api/config -- the poll loop watches this and
# reconnects whenever it changes.
_config = {"draft_id": None, "my_draft_slot": 1, "data_source": DEFAULT_DATA_SOURCE}

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
    data_source: str = DEFAULT_DATA_SOURCE


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
    active_data_source = None
    engine = projections_csv = None
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
            desired_data_source = _config["data_source"]

        if desired_draft_id is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if (
            desired_draft_id != active_draft_id
            or desired_slot != my_draft_slot
            or desired_data_source != active_data_source
        ):
            active_draft_id = desired_draft_id
            my_draft_slot = desired_slot
            active_data_source = desired_data_source
            engine, projections_csv = DATA_SOURCES.get(
                active_data_source, DATA_SOURCES[DEFAULT_DATA_SOURCE]
            )
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
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            settings = status.get("settings", {})
            teams = settings.get("teams", 12)
            total_rounds = settings.get("rounds", 15)
            # .get(..., 60) only falls back when the key is missing -- Sleeper
            # returns pick_timer=0 for untimed/fast mock drafts (a real,
            # present value meaning "no clock enforced"), which slipped past
            # that default and silently zeroed out eta_seconds downstream
            # (picks_away * 0 == 0 regardless of how many picks away we are).
            pick_timer = settings.get("pick_timer") or 60
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
                time.sleep(POLL_INTERVAL_SECONDS)
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
            time.sleep(POLL_INTERVAL_SECONDS)
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

            drafted_names = engine.get_drafted_names(picks)
            t0 = time.monotonic()
            archetypal_candidates = engine.generate_pareto_candidate_stream(
                drafted_names,
                projections_csv,
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
                    "roster_archetype_detected": engine.detect_roster_archetype(roster, round_num),
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

        logger.info(
            "poll tick for pick #%s: %.2fs total (%s picks away, before %ss sleep)",
            current_pick_no,
            time.monotonic() - tick_start,
            picks_away,
            POLL_INTERVAL_SECONDS,
        )
        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def _start_poll_loop() -> None:
    # Configured here, not at module import time: uvicorn's own startup
    # calls logging.config.dictConfig() internally, which unconditionally
    # closes every previously-installed handler via the stdlib's
    # _clearExistingHandlers() -- regardless of disable_existing_loggers --
    # so a basicConfig() call at import time gets silently torn down before
    # this app ever logs anything. Calling it here, after uvicorn's own
    # logging setup has already run (its dictConfig happens during
    # Server.serve(), before the ASGI "startup" event fires), makes it
    # actually stick.
    logging.basicConfig(
        filename=LOG_FILE,
        filemode="w",  # fresh log each server start, not an unbounded append across dev sessions
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    threading.Thread(target=_poll_loop, daemon=True).start()


@app.get("/api/config")
def get_config() -> dict:
    with _lock:
        return dict(_config)


@app.post("/api/config")
def set_config(update: ConfigUpdate) -> dict:
    if update.data_source not in DATA_SOURCES:
        return {"error": f"Unknown data_source '{update.data_source}'. Valid: {list(DATA_SOURCES)}"}
    with _lock:
        _config["draft_id"] = update.draft_id
        _config["my_draft_slot"] = update.my_draft_slot
        _config["data_source"] = update.data_source
        _state["error"] = None
    return {
        "draft_id": update.draft_id,
        "my_draft_slot": update.my_draft_slot,
        "data_source": update.data_source,
    }


@app.post("/api/rotoballer/refresh")
def refresh_rotoballer() -> dict:
    """Fetches fresh RotoBaller rankings and rewrites data/projections_rb.csv
    in place. Same trigger/response shape as the FantasyPros refresh below.
    """
    try:
        df, source = update_data_rotoballer.build_draft_board()
    except Exception as exc:
        logger.warning("RotoBaller refresh failed: %s", exc)
        return {"success": False, "error": f"Fetch failed: {exc}"}

    csv_path = DATA_SOURCES["rotoballer"][1]
    df.to_csv(csv_path, index=False)
    draft_math_rb._league_baseline_lineup.cache_clear()

    return {
        "success": True,
        "player_count": len(df),
        "by_position": df["position"].value_counts().to_dict(),
        "source": source,
    }


@app.post("/api/draftsharks/refresh")
def refresh_draftsharks() -> dict:
    """Fetches fresh DraftSharks rankings and rewrites data/projections_ds.csv
    in place. Same trigger/response shape as the FantasyPros refresh below.
    """
    try:
        df = update_data_draftsharks.fetch_all()
    except Exception as exc:
        logger.warning("DraftSharks refresh failed: %s", exc)
        return {"success": False, "error": f"Fetch failed: {exc}"}

    if len(df) < update_data_draftsharks.MIN_VALID_PLAYERS:
        return {
            "success": False,
            "error": (
                f"Only parsed {len(df)} valid players "
                f"(< {update_data_draftsharks.MIN_VALID_PLAYERS}); "
                "draftsharks.com likely changed its markup."
            ),
        }

    csv_path = DATA_SOURCES["draftsharks"][1]
    df.to_csv(csv_path, index=False)
    draft_math_ds._league_baseline_lineup.cache_clear()

    return {
        "success": True,
        "player_count": len(df),
        "by_position": df["position"].value_counts().to_dict(),
    }


@app.post("/api/fantasypros/refresh")
def refresh_fantasypros() -> dict:
    """Fetches fresh FantasyPros ECR + projections and rewrites
    data/projections_fp.csv in place. Called from the frontend's 'Refresh
    FantasyPros Data' button, not from the poll loop. No auth needed -- see
    update_data_fantasypros.py's module docstring for why.
    """
    try:
        df = update_data_fantasypros.build_draft_board()
    except update_data_fantasypros.FantasyProsAPIError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("FantasyPros refresh failed: %s", exc)
        return {"success": False, "error": f"Fetch failed: {exc}"}

    csv_path = DATA_SOURCES["fantasypros"][1]
    df.to_csv(csv_path, index=False)
    # _league_baseline_lineup is lru_cache'd by csv_path string -- since this
    # rewrites the same path in place, the cache would otherwise keep
    # serving the pre-refresh baseline for the rest of the process lifetime.
    draft_math_fp._league_baseline_lineup.cache_clear()

    return {
        "success": True,
        "player_count": len(df),
        "by_position": df["position"].value_counts().to_dict(),
    }


@app.post("/api/hybrid/refresh")
def refresh_hybrid() -> dict:
    """Rebuilds data/projections_hybrid.csv from whatever's currently on disk
    for RB/DS/FP -- a local merge, not a network fetch (see
    update_data_hybrid.py's module docstring). Refresh those three first if
    you want the hybrid to reflect fresh data; this endpoint just re-merges
    whatever's already there.
    """
    try:
        df = update_data_hybrid.build_hybrid_board()
        if len(df) < update_data_hybrid.MIN_VALID_PLAYERS:
            return {
                "success": False,
                "error": (
                    f"Hybrid merge produced only {len(df)} players "
                    f"(< {update_data_hybrid.MIN_VALID_PLAYERS}) -- refresh RB/DS/FP first."
                ),
            }
    except Exception as exc:
        logger.warning("Hybrid refresh failed: %s", exc)
        return {"success": False, "error": f"Merge failed: {exc}"}

    csv_path = DATA_SOURCES["hybrid"][1]
    df.to_csv(csv_path, index=False)
    draft_math_hybrid._league_baseline_lineup.cache_clear()

    return {
        "success": True,
        "player_count": len(df),
        "by_position": df["position"].value_counts().to_dict(),
    }


@app.get("/api/state")
def get_state() -> dict:
    return _snapshot_state()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return TEMPLATE_PATH.read_text()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
