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
}

interface LineupResponse {
  week: number;
  starters: LineupPlayer[];
  bench: LineupPlayer[];
  total_projected_points: number;
  unresolved_player_ids: string[];
}

function PlayerRow({ player }: { player: LineupPlayer }) {
  return (
    <li>
      {player.slot ? `${player.slot}: ` : ""}
      {player.name ?? player.player_id} ({player.position}
      {player.team ? `, ${player.team}` : ""}) — {player.projected_points.toFixed(1)} pts
      {player.injury_status && (
        <span className="injury-badge"> {player.injury_status}</span>
      )}
    </li>
  );
}

export default function Lineup() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [week, setWeek] = useState<number | null>(null);
  const [lineup, setLineup] = useState<LineupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLineup(null);
    setError(null);
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

  return (
    <div className="page">
      <h1>Week {week ?? "..."} Lineup</h1>
      {error && <p className="error">{error}</p>}
      {!lineup && !error && <p>Loading...</p>}
      {lineup && (
        <>
          <p>Projected total: {lineup.total_projected_points.toFixed(1)} pts</p>
          <h2>Starters</h2>
          <ul>
            {lineup.starters.map((p) => (
              <PlayerRow key={p.player_id} player={p} />
            ))}
          </ul>
          <h2>Bench</h2>
          <ul>
            {lineup.bench.map((p) => (
              <PlayerRow key={p.player_id} player={p} />
            ))}
          </ul>
          {lineup.unresolved_player_ids.length > 0 && (
            <p className="error">
              No projection available this week for: {lineup.unresolved_player_ids.join(", ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
