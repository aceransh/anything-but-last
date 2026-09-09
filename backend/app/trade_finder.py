"""Pure, DB/network-free multi-team trade discovery -- builds a directed
graph of managers where an edge u -> v exists when some 1- or 2-player
package from u's roster gives v positive marginal starting-lineup value,
then searches for elementary cycles through one fixed manager (the
searching user) up to a bounded length. Reuses optimize_lineup from
lineup_math.py for every marginal-value calculation; surviving candidates
are handed to trade_math.evaluate_trade by the router for the real,
per-week-validated verdict -- this module never scores a trade itself.

Follows the research PDF's "Multi-Team Graph-Based Trade Finder" model
(managers as vertices, profitable asset transfers as edges, elementary
circuits as viable N-team trades), with three deliberate simplifications
for tractability -- see CLAUDE.md's "Multi-Team Trade Finder" section for
the full reasoning:

1. Only the top TOP_N_SINGLES individual players (by marginal value) are
   considered when forming 2-player packages, bounding the work per edge
   to a constant regardless of roster size.
2. Each directed edge stores only its single highest-marginal-value
   package, not every viable one -- keeps the graph a plain digraph
   rather than a multigraph.
3. Cycle search is a bounded depth-first search rooted at one fixed
   vertex rather than general Johnson's algorithm -- mathematically
   equivalent for "cycles through one fixed node up to length k", far
   less code, and no new dependency.
"""

from .lineup_math import optimize_lineup

TOP_N_SINGLES = 5


def player_marginal_value(
    pool: list[dict], slot_requirements: dict[str, int], additional_players: list[dict]
) -> float:
    """The lineup-point gain from adding additional_players to pool --
    positive only if at least one of them would actually start."""
    baseline = optimize_lineup(pool, slot_requirements)["total_projected_points"]
    with_additions = optimize_lineup(pool + additional_players, slot_requirements)[
        "total_projected_points"
    ]
    return with_additions - baseline


def best_package(
    giver_pool: list[dict], receiver_pool: list[dict], slot_requirements: dict[str, int]
) -> dict | None:
    """The single highest-marginal-value package (1 or 2 players) giver
    could send receiver. Pairs are only formed among the top
    TOP_N_SINGLES individual players by marginal value -- see module
    docstring. Returns None if nothing clears a positive gain.
    """
    singles = [
        {
            "player_ids": [p["player_id"]],
            "marginal_value": player_marginal_value(receiver_pool, slot_requirements, [p]),
        }
        for p in giver_pool
    ]
    singles.sort(key=lambda s: -s["marginal_value"])
    top_singles = singles[:TOP_N_SINGLES]

    by_id = {p["player_id"]: p for p in giver_pool}
    candidates = list(top_singles)
    for i, a in enumerate(top_singles):
        for b in top_singles[i + 1 :]:
            pair_players = [by_id[a["player_ids"][0]], by_id[b["player_ids"][0]]]
            value = player_marginal_value(receiver_pool, slot_requirements, pair_players)
            candidates.append({"player_ids": a["player_ids"] + b["player_ids"], "marginal_value": value})

    if not candidates:
        return None
    best = max(candidates, key=lambda c: c["marginal_value"])
    return best if best["marginal_value"] > 0 else None


def build_trade_graph(
    rosters: dict[int, list[dict]], slot_requirements: dict[str, int]
) -> dict[tuple[int, int], dict]:
    """One entry per ordered manager pair with a positive-value package."""
    edges: dict[tuple[int, int], dict] = {}
    for u, giver_pool in rosters.items():
        for v, receiver_pool in rosters.items():
            if u == v:
                continue
            package = best_package(giver_pool, receiver_pool, slot_requirements)
            if package is not None:
                edges[(u, v)] = package
    return edges


def find_cycles_through(
    root_roster_id: int, edges: dict[tuple[int, int], dict], max_length: int = 4
) -> list[list[int]]:
    """Elementary cycles (m_1, ..., m_k) with m_1 == root_roster_id, 2 <=
    k <= max_length, meaning m_1 -> m_2 -> ... -> m_k -> m_1 are all real
    edges. A bounded DFS rather than general Johnson's algorithm -- see
    module docstring for why that's the right tradeoff here.
    """
    adjacency: dict[int, list[int]] = {}
    for u, v in edges:
        adjacency.setdefault(u, []).append(v)

    cycles: list[list[int]] = []

    def dfs(path: list[int], visited: set[int]) -> None:
        current = path[-1]
        for neighbor in adjacency.get(current, []):
            if neighbor == root_roster_id:
                if len(path) >= 2:
                    cycles.append(list(path))
                continue
            if neighbor in visited or len(path) >= max_length:
                continue
            visited.add(neighbor)
            dfs(path + [neighbor], visited)
            visited.discard(neighbor)

    dfs([root_roster_id], {root_roster_id})
    return cycles


def rank_by_edge_value(cycles: list[list[int]], edges: dict[tuple[int, int], dict]) -> list[list[int]]:
    """Fast phase-1 sort key (sum of each leg's marginal value) used to
    cap candidates before the expensive per-week validation -- not the
    final ranking shown to the user, which uses the real validated
    differential instead (see routers/trade.py).
    """

    def cycle_score(cycle: list[int]) -> float:
        total = 0.0
        for i, u in enumerate(cycle):
            v = cycle[(i + 1) % len(cycle)]
            total += edges[(u, v)]["marginal_value"]
        return total

    return sorted(cycles, key=cycle_score, reverse=True)


def cycle_to_moves(cycle: list[int], edges: dict[tuple[int, int], dict]) -> list[dict]:
    """Expands each leg's package into individual {player_id,
    from_roster_id, to_roster_id} moves -- a 2-player package becomes 2
    moves, exactly the shape trade_math.evaluate_trade already expects.
    """
    moves = []
    for i, u in enumerate(cycle):
        v = cycle[(i + 1) % len(cycle)]
        for player_id in edges[(u, v)]["player_ids"]:
            moves.append({"player_id": player_id, "from_roster_id": u, "to_roster_id": v})
    return moves
