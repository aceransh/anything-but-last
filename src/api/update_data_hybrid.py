"""Merges the three already-fetched projection CSVs (RotoBaller, DraftSharks,
FantasyPros) into data/projections_hybrid.csv.

Unlike the other three update_data_*.py scripts, this one makes NO network
calls -- it's a pure local merge of data those scripts already wrote to disk.
Run this AFTER refreshing all three:

    .venv/bin/python -m src.api.update_data_rotoballer
    .venv/bin/python -m src.api.update_data_draftsharks
    .venv/bin/python -m src.api.update_data_fantasypros
    .venv/bin/python -m src.api.update_data_hybrid

Merge rules (see CLAUDE.md's "Hybrid Engine Variant" section for the full
research behind these choices):
- Players are matched across sources on a normalized (name, position) key --
  suffixes (Jr./Sr./II/III/IV) and punctuation stripped, case-folded. This
  recovers ~6.6% more cross-source matches than exact string matching (e.g.
  "Patrick Mahomes II" vs "Patrick Mahomes", "D.J. Moore" vs "DJ Moore").
  The displayed player_name is RotoBaller's spelling where available (the
  existing Sleeper-name-matching heuristics in draft_math_rb.py's
  `_drafted_mask` were tuned against RotoBaller's naming), else FantasyPros',
  else DraftSharks'.
- projected_points = median of whichever of {RB, DS, FP} have the player.
  Median (not mean) because per-source disagreement is real signal, not
  noise (median spread ~12% of the 3-source mean, worse for QBs) but a
  single source occasionally drops a 0-point placeholder row that would
  drag a mean down hard; median is immune to that without adding a new
  tunable weight constant.
- adp = median of whichever REAL ADP sources have the player (RotoBaller's
  industry_avg, DraftSharks' round.pick-derived value). FantasyPros' `adp`
  column is actually ECR (Expert Consensus Rank), not real draft position --
  it's used ONLY as a last-resort fallback when neither RB nor DS has ranked
  the player at all. Real market ADP always wins over the ECR proxy when
  available.
- floor_points/ceiling_points are carried through from DraftSharks' row
  where matched, else left null. draft_math_hybrid.py's `_hybrid_std_dev`
  uses these when present and falls back to the synthetic heuristic
  otherwise -- these columns are referenced nowhere else in the engine, so
  carrying them for only ~half the pool can't break anything downstream.
"""

import re

import pandas as pd

RB_CSV = "data/projections_rb.csv"
DS_CSV = "data/projections_ds.csv"
FP_CSV = "data/projections_fp.csv"
OUTPUT_CSV = "data/projections_hybrid.csv"

# A merge that comes out much smaller than this almost certainly means one
# of the three source CSVs failed to load or is stale/empty -- not a real
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


def _clean_adp(series: pd.Series) -> pd.Series:
    """RotoBaller uses 0.0 as an "unranked" sentinel for deep bench/K rows --
    treated as missing here, same as a real NaN, so it never outranks an
    actual early-round ADP in a median.
    """
    cleaned = pd.to_numeric(series, errors="coerce")
    return cleaned.where(cleaned > 0)


def _load(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["team"] = df["team"].astype(str).str.upper().replace(TEAM_CODE_ALIASES)
    df["position"] = df["position"].astype(str).str.upper()
    df["key"] = (df["player_name"] + "|" + df["position"]).apply(
        lambda s: normalize_key(s.rsplit("|", 1)[0]) + "|" + s.rsplit("|", 1)[1]
    )
    df["adp"] = _clean_adp(df["adp"])
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
    player drafted.
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
    rb = _load(RB_CSV)
    ds = _load(DS_CSV)
    fp = _load(FP_CSV)

    groups = _build_key_groups([rb, ds, fp])
    rb["key"] = rb["key"].map(groups)
    ds["key"] = ds["key"].map(groups)
    fp["key"] = fp["key"].map(groups)

    rb_idx = rb.set_index("key")
    ds_idx = ds.set_index("key")
    fp_idx = fp.set_index("key")

    all_keys = sorted(set(rb_idx.index) | set(ds_idx.index) | set(fp_idx.index))

    rows = []
    for key in all_keys:
        rb_row = rb_idx.loc[key] if key in rb_idx.index else None
        ds_row = ds_idx.loc[key] if key in ds_idx.index else None
        fp_row = fp_idx.loc[key] if key in fp_idx.index else None

        position = key.rsplit("|", 1)[1]
        player_name = next(
            row["player_name"] for row in (rb_row, fp_row, ds_row) if row is not None
        )
        team = next(
            (row["team"] for row in (rb_row, fp_row, ds_row) if row is not None), ""
        )

        points = [
            row["projected_points"]
            for row in (rb_row, ds_row, fp_row)
            if row is not None and pd.notna(row["projected_points"])
        ]
        if not points:
            continue
        projected_points = float(pd.Series(points).median())

        real_adp = [
            row["adp"] for row in (rb_row, ds_row) if row is not None and pd.notna(row["adp"])
        ]
        if real_adp:
            adp = float(pd.Series(real_adp).median())
        elif fp_row is not None and pd.notna(fp_row["adp"]):
            adp = float(fp_row["adp"])
        else:
            adp = float("nan")

        rows.append(
            {
                "player_name": player_name,
                "position": position,
                "team": team,
                "projected_points": projected_points,
                "adp": adp,
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
            "one of the three source CSVs likely failed to load. Refresh RB/DS/FP first."
        )
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} players to {OUTPUT_CSV}")
    print(df["position"].value_counts().to_string())


if __name__ == "__main__":
    main()
