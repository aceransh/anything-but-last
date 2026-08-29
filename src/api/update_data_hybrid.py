"""Merges the four already-fetched projection CSVs (RotoBaller, DraftSharks,
FantasyPros, Sleeper) into data/projections_hybrid.csv.

Unlike the other four update_data_*.py scripts, this one makes NO network
calls -- it's a pure local merge of data those scripts already wrote to disk.
Run this AFTER refreshing all four:

    .venv/bin/python -m src.api.update_data_rotoballer
    .venv/bin/python -m src.api.update_data_draftsharks
    .venv/bin/python -m src.api.update_data_fantasypros
    .venv/bin/python -m src.api.update_data_sl
    .venv/bin/python -m src.api.update_data_hybrid

This is a rewrite (per "Architectural Evaluation and Hybrid Engine Design for
Real-Time Draft Optimization", a research PDF the user supplied) of an
earlier version that only merged RB/DS/FP with a single blended `adp`
column. The new design's central idea is to decouple MARKET MECHANICS
(how opponents actually behave in a live Sleeper draft room) from PLAYER
EVALUATION (projection/variance quality), which this file and
draft_math_hybrid.py implement together:

- projected_points = a coverage-adjusted dynamic median across whichever of
  {RB, DS, FP, SL} have a valid projection for the player. `source_count`
  (the PDF's |S_i|) is written alongside it -- draft_math_hybrid.py's
  variance model needs to know how many independent sources agree.
- sigma_cross (cross-source projection dispersion, the PDF's sigma_cross) is
  precomputed HERE, not in the live engine -- it only needs to be computed
  once per player during offline ingestion, matching the PDF's explicit
  latency guidance (all entity resolution / median blending / variance
  weighting happens pre-draft; live-loop reads must stay well under the
  30-second pick clock).
- TWO separate ADP tracks, not one:
    adp_local  = Sleeper's own platform ADP (SL only, unmerged). This is
                 the room this app actually drafts in, so
                 draft_math_hybrid.py uses it exclusively for survival-
                 probability / hazard-rate modeling (how opponents in THIS
                 draft room actually behave).
    adp_global = FantasyPros' real cross-platform ADP, falling back to
                 adp_local when FP has no data for a player (~40% of its
                 extended board, per FantasyPros' own coverage), then to a
                 median(RB, DS) real-ADP fallback for the rare remaining
                 gap. draft_math_hybrid.py uses this for reach-penalty
                 scoring, Dead-Zone RB banding, and the "Expert Buy-Low"
                 tag -- all genuinely global-market concepts, where scoring
                 a candidate against Sleeper's own room-specific ADP would
                 wrongly penalize a pick that only looks early because of
                 this one platform's quirks, not the real market.
    adp        = kept as a legacy alias for adp_global, so any code
                 expecting a single `adp` column (e.g. the bot-drafting
                 sort in test_draft_simulation_hybrid.py) keeps working
                 unchanged -- and now sorts by genuine market ADP rather
                 than the old RB/DS-median approach. This is a deliberate
                 behavior change, not an oversight.
- ecr (FantasyPros' Expert Consensus Rank) is carried through for the first
  time here -- previously a known gap (see CLAUDE.md) -- needed for the
  ported "Expert Buy-Low" tag in draft_math_hybrid.py.

Three deliberate deviations from the PDF's literal design, confirmed with
the user before implementing (see CLAUDE.md's "Hybrid Engine Variant"
section for the full reasoning):
1. Entity resolution uses the existing zero-dependency union-find matcher
   (extended to 4 sources) instead of the PDF's suggested RapidFuzz -- no
   new dependency added, and the union-find approach was already proven in
   production for this exact nickname-mismatch problem.
2. The matching key is (name, position) only, NOT (name, position, team) as
   the PDF's literal formula states -- matching on team risks a real
   correctness regression: a source that hasn't yet reflected a recent
   trade would silently split one player into two rows instead of merging
   them.
3. The "Expert Buy-Low" sign convention is adp_global - ecr >= tau_buy
   (matches the PDF's own prose, and the already-shipped FantasyPros
   engine's tag) rather than the PDF's literal formula
   (ecr - adp_global >= tau_buy), which contradicts its own prose and would
   flag the opposite signal.

Merge rules (see CLAUDE.md's "Hybrid Engine Variant" section for the full
research behind these choices):
- Players are matched across sources on a normalized (name, position) key --
  suffixes (Jr./Sr./II/III/IV) and punctuation stripped, case-folded. This
  recovers real cross-source matches that exact string matching misses (e.g.
  "Patrick Mahomes II" vs "Patrick Mahomes", "D.J. Moore" vs "DJ Moore"),
  plus a union-find pass (`_build_key_groups`) that additionally fuses
  nickname mismatches (e.g. "Kenny" vs "Kenneth" Gainwell) via unambiguous
  (last_name, position) pairs within each source.
- The displayed player_name/team prefers Sleeper's spelling first (Sleeper
  is now the widest single source, and -- more importantly -- it's the
  literal source of live draft-pick metadata this app matches drafted
  players against, so preferring its spelling minimizes residual name-
  mismatch risk downstream in `_drafted_mask`), then RotoBaller's, then
  FantasyPros', then DraftSharks'.
- floor_points/ceiling_points are carried through from DraftSharks' row
  where matched, else left null. draft_math_hybrid.py's `_hybrid_variance`
  uses these when present.
"""

import re

import pandas as pd

RB_CSV = "data/projections_rb.csv"
DS_CSV = "data/projections_ds.csv"
FP_CSV = "data/projections_fp.csv"
SL_CSV = "data/projections_sl.csv"
OUTPUT_CSV = "data/projections_hybrid.csv"

# A merge that comes out much smaller than this almost certainly means one
# of the four source CSVs failed to load or is stale/empty -- not a real
# reflection of the player pool.
MIN_VALID_PLAYERS = 300

TEAM_CODE_ALIASES = {"JAC": "JAX", "LVR": "LV"}

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[.\'\-]")


def normalize_key(name: str) -> str:
    """Case/punctuation/suffix-insensitive key used ONLY for cross-source
    matching -- the display name shown to the user is never this value.
    """
    name = _PUNCT_RE.sub("", name.strip().lower())
    name = _SUFFIX_RE.sub("", name.strip()).strip()
    return re.sub(r"\s+", " ", name)


def _clean_adp(series: pd.Series, sentinel: float | None = None) -> pd.Series:
    """Treats a source-specific "unranked" sentinel as missing (same as a
    real NaN) before the generic non-positive filter runs, so it never
    outranks a genuine early-round ADP in a median or fallback chain.
    RotoBaller uses 0.0 for deep bench/K rows; Sleeper uses 999.0 for
    players with no real ADP consensus (confirmed against its live API
    response -- see src/api/update_data_sl.py). DraftSharks and FantasyPros
    need no sentinel; they already emit NaN for missing ADP.
    """
    cleaned = pd.to_numeric(series, errors="coerce")
    if sentinel is not None:
        cleaned = cleaned.where(cleaned != sentinel)
    return cleaned.where(cleaned > 0)


def _load(csv_path: str, adp_sentinel: float | None = None) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["team"] = df["team"].astype(str).str.upper().replace(TEAM_CODE_ALIASES)
    df["position"] = df["position"].astype(str).str.upper()
    df["key"] = (df["player_name"] + "|" + df["position"]).apply(
        lambda s: normalize_key(s.rsplit("|", 1)[0]) + "|" + s.rsplit("|", 1)[1]
    )
    df["adp"] = _clean_adp(df["adp"], sentinel=adp_sentinel)
    return df


def _last_name_pos(key: str) -> tuple[str, str]:
    name_part, position = key.rsplit("|", 1)
    last = name_part.split(" ")[-1] if name_part else name_part
    return last, position


def _find(parent: dict, x: str) -> str:
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict, a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


def _build_key_groups(frames: list) -> dict:
    """Maps every row's `key` to a canonical group id, fusing keys across
    sources that share a (last_name, position) pair -- but ONLY when that
    pair is unambiguous (exactly one row) WITHIN EACH source it appears in.
    This is the exact same rule draft_math_hybrid.py's `_drafted_mask` uses
    to catch nickname mismatches (e.g. "Kenny Gainwell" vs "Kenneth
    Gainwell") without a hardcoded nickname table -- applied here because a
    plain normalize_key() match alone doesn't catch nicknames (only
    suffixes/punctuation/case), so real players like Kenny/Kenneth Gainwell,
    Cam/Cameron Skattebo, Cam/Cameron Ward, Andy/Andres Borregales, and
    Chig/Chigoziem Okonkwo were ending up as TWO separate hybrid rows. That
    silently broke _drafted_mask's OWN fallback downstream: it refuses to
    fire once a (last_name, position) pair isn't unique in the pool, which
    becomes true the moment a duplicate like this exists -- so one of the
    two rows kept showing as available even after Sleeper reported the
    player drafted. Generalizes to any number of source frames -- extending
    from 3 to 4 sources (adding Sleeper) required no change to this
    function, only to its caller's frame list.
    """
    parent: dict = {}
    pair_to_keys: dict = {}
    for df in frames:
        pairs = df["key"].apply(_last_name_pos)
        counts = pairs.value_counts()
        for key, pair in zip(df["key"], pairs):
            _find(parent, key)
            if counts[pair] == 1:  # unambiguous within this one source
                pair_to_keys.setdefault(pair, set()).add(key)
    for keys in pair_to_keys.values():
        keys = list(keys)
        for other in keys[1:]:
            _union(parent, keys[0], other)
    return {key: _find(parent, key) for key in parent}


def build_hybrid_board() -> pd.DataFrame:
    sl = _load(SL_CSV, adp_sentinel=999.0)
    rb = _load(RB_CSV, adp_sentinel=0.0)
    ds = _load(DS_CSV)
    fp = _load(FP_CSV)

    groups = _build_key_groups([sl, rb, ds, fp])
    sl["key"] = sl["key"].map(groups)
    rb["key"] = rb["key"].map(groups)
    ds["key"] = ds["key"].map(groups)
    fp["key"] = fp["key"].map(groups)

    sl_idx = sl.set_index("key")
    rb_idx = rb.set_index("key")
    ds_idx = ds.set_index("key")
    fp_idx = fp.set_index("key")

    all_keys = sorted(
        set(sl_idx.index) | set(rb_idx.index) | set(ds_idx.index) | set(fp_idx.index)
    )

    rows = []
    for key in all_keys:
        sl_row = sl_idx.loc[key] if key in sl_idx.index else None
        rb_row = rb_idx.loc[key] if key in rb_idx.index else None
        ds_row = ds_idx.loc[key] if key in ds_idx.index else None
        fp_row = fp_idx.loc[key] if key in fp_idx.index else None

        position = key.rsplit("|", 1)[1]
        player_name = next(
            row["player_name"]
            for row in (sl_row, rb_row, fp_row, ds_row)
            if row is not None
        )
        team = next(
            (row["team"] for row in (sl_row, rb_row, fp_row, ds_row) if row is not None),
            "",
        )

        points = [
            row["projected_points"]
            for row in (sl_row, rb_row, ds_row, fp_row)
            if row is not None and pd.notna(row["projected_points"])
        ]
        if not points:
            continue
        source_count = len(points)
        projected_points = float(pd.Series(points).median())
        sigma_cross = (
            float(pd.Series(points).std(ddof=1)) if source_count >= 2 else float("nan")
        )

        adp_local = float(sl_row["adp"]) if sl_row is not None and pd.notna(sl_row["adp"]) else float("nan")

        if fp_row is not None and pd.notna(fp_row["adp"]):
            adp_global = float(fp_row["adp"])
        elif pd.notna(adp_local):
            adp_global = adp_local
        else:
            fallback_real_adp = [
                row["adp"] for row in (rb_row, ds_row) if row is not None and pd.notna(row["adp"])
            ]
            adp_global = float(pd.Series(fallback_real_adp).median()) if fallback_real_adp else float("nan")

        rows.append(
            {
                "player_name": player_name,
                "position": position,
                "team": team,
                "projected_points": projected_points,
                "source_count": source_count,
                "sigma_cross": sigma_cross,
                "adp": adp_global,
                "adp_local": adp_local,
                "adp_global": adp_global,
                "ecr": float(fp_row["ecr"]) if fp_row is not None and pd.notna(fp_row.get("ecr")) else float("nan"),
                "floor_points": ds_row["floor_points"] if ds_row is not None else float("nan"),
                "ceiling_points": ds_row["ceiling_points"] if ds_row is not None else float("nan"),
            }
        )

    df = pd.DataFrame(rows)
    return df.sort_values("projected_points", ascending=False).reset_index(drop=True)


def main() -> None:
    df = build_hybrid_board()
    if len(df) < MIN_VALID_PLAYERS:
        raise RuntimeError(
            f"Hybrid merge produced only {len(df)} players (< {MIN_VALID_PLAYERS}) -- "
            "one of the four source CSVs likely failed to load. Refresh RB/DS/FP/SL first."
        )
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} players to {OUTPUT_CSV}")
    print(df["position"].value_counts().to_string())


if __name__ == "__main__":
    main()
