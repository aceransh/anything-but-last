import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiFetch } from "../lib/api";

interface LineupPlayer {
  player_id: string;
  position: string;
  projected_points: number;
  name: string | null;
  team: string | null;
  injury_status: string | null;
  slot: string | null;
  same_team_stack_with: string | null;
  injury_warning: boolean;
}

interface AlternateLineup {
  starters: LineupPlayer[];
  bench: LineupPlayer[];
  total_projected_points: number;
  swapped_out: string[];
}

interface UnresolvedPlayer {
  player_id: string;
  reason: "bye" | "no_projection";
}

interface LineupResponse {
  week: number;
  starters: LineupPlayer[];
  bench: LineupPlayer[];
  total_projected_points: number;
  unresolved_players: UnresolvedPlayer[];
  alternate_lineup: AlternateLineup | null;
}

function PlayerRow({
  player,
  nameById,
}: {
  player: LineupPlayer;
  nameById: Map<string, string>;
}) {
  return (
    <li>
      {player.slot ? `${player.slot}: ` : ""}
      {player.name ?? player.player_id} ({player.position}
      {player.team ? `, ${player.team}` : ""}) — {player.projected_points.toFixed(1)} pts
      {player.injury_warning ? (
        <span className="injury-warning"> ⚠ Starting a player who is {player.injury_status}</span>
      ) : (
        player.injury_status && <span className="injury-badge"> {player.injury_status}</span>
      )}
      {player.same_team_stack_with && (
        <span className="stack-badge">
          {" "}
          shares targets with {nameById.get(player.same_team_stack_with) ?? player.same_team_stack_with}
        </span>
      )}
    </li>
  );
}

export default function Lineup() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [week, setWeek] = useState<number | null>(null);
  const [lineup, setLineup] = useState<LineupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAlternate, setShowAlternate] = useState(false);

  useEffect(() => {
    setLineup(null);
    setError(null);
    setShowAlternate(false);
    const query = week ? `?week=${week}` : "";
    apiFetch(`/leagues/${leagueId}/lineup${query}`)
      .then((res) => res.json())
      .then((data: LineupResponse) => {
        setLineup(data);
        setWeek(data.week);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load lineup"),
      );
  }, [leagueId, week]);

  const nameById = new Map(
    lineup ? lineup.starters.map((p) => [p.player_id, p.name ?? p.player_id]) : [],
  );

  const active = showAlternate && lineup?.alternate_lineup ? lineup.alternate_lineup : lineup;

  return (
    <div className="page">
      <h1>Week {week ?? "..."} Lineup</h1>
      {error && <p className="error">{error}</p>}
      {!lineup && !error && <p>Loading...</p>}
      {lineup && active && (
        <>
          <p>Projected total: {active.total_projected_points.toFixed(1)} pts</p>
          {lineup.alternate_lineup && (
            <button type="button" onClick={() => setShowAlternate(!showAlternate)}>
              {showAlternate ? "Show original lineup" : "Show alternate lineup (avoids same-team stacks)"}
            </button>
          )}
          {showAlternate && lineup.alternate_lineup && (
            <p>
              Swaps out{" "}
              {lineup.alternate_lineup.swapped_out
                .map((id) => nameById.get(id) ?? id)
                .join(", ")}{" "}
              for the cost of {(lineup.total_projected_points - lineup.alternate_lineup.total_projected_points).toFixed(1)}{" "}
              projected points.
            </p>
          )}
          <h2>Starters</h2>
          <ul>
            {active.starters.map((p) => (
              <PlayerRow key={p.player_id} player={p} nameById={nameById} />
            ))}
          </ul>
          <h2>Bench</h2>
          <ul>
            {active.bench.map((p) => (
              <PlayerRow key={p.player_id} player={p} nameById={nameById} />
            ))}
          </ul>
          {lineup.unresolved_players.some((p) => p.reason === "bye") && (
            <p>
              On bye:{" "}
              {lineup.unresolved_players
                .filter((p) => p.reason === "bye")
                .map((p) => p.player_id)
                .join(", ")}
            </p>
          )}
          {lineup.unresolved_players.some((p) => p.reason === "no_projection") && (
            <p className="error">
              No projection available this week (likely on bye or unmodeled):{" "}
              {lineup.unresolved_players
                .filter((p) => p.reason === "no_projection")
                .map((p) => p.player_id)
                .join(", ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
