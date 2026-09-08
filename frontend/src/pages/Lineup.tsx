import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Card from "@/components/Card";
import PlayerRow from "@/components/PlayerRow";
import { Button } from "@/components/ui/button";
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

function PlayerList({ players, nameById }: { players: LineupPlayer[]; nameById: Map<string, string> }) {
  return (
    <ul>
      {players.map((p) => (
        <PlayerRow
          key={p.player_id}
          playerId={p.player_id}
          position={p.position}
          name={p.name}
          team={p.team}
          points={p.projected_points}
          injuryStatus={p.injury_status}
          injuryLoud={p.injury_warning}
          slot={p.slot}
          note={
            p.same_team_stack_with
              ? `Shares targets with ${nameById.get(p.same_team_stack_with) ?? p.same_team_stack_with}`
              : undefined
          }
        />
      ))}
    </ul>
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
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-xl font-bold text-foreground">Week {week ?? "..."} Lineup</h1>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!lineup && !error && <p className="text-muted-foreground">Loading...</p>}
      {lineup && active && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Projected total:{" "}
              <span className="font-semibold text-foreground">
                {active.total_projected_points.toFixed(1)} pts
              </span>
            </p>
            {lineup.alternate_lineup && (
              <Button variant="outline" size="sm" onClick={() => setShowAlternate(!showAlternate)}>
                {showAlternate ? "Show original lineup" : "Show de-stacked alternate"}
              </Button>
            )}
          </div>
          {showAlternate && lineup.alternate_lineup && (
            <p className="text-sm text-amber-500">
              Swaps out{" "}
              {lineup.alternate_lineup.swapped_out.map((id) => nameById.get(id) ?? id).join(", ")}{" "}
              for the cost of{" "}
              {(lineup.total_projected_points - lineup.alternate_lineup.total_projected_points).toFixed(1)}{" "}
              projected points.
            </p>
          )}

          <Card>
            <h2 className="mb-2 text-sm font-semibold text-muted-foreground">Starters</h2>
            <PlayerList players={active.starters} nameById={nameById} />
          </Card>

          <Card>
            <h2 className="mb-2 text-sm font-semibold text-muted-foreground">Bench</h2>
            <PlayerList players={active.bench} nameById={nameById} />
          </Card>

          {lineup.unresolved_players.some((p) => p.reason === "bye") && (
            <p className="text-sm text-muted-foreground">
              On bye:{" "}
              {lineup.unresolved_players
                .filter((p) => p.reason === "bye")
                .map((p) => p.player_id)
                .join(", ")}
            </p>
          )}
          {lineup.unresolved_players.some((p) => p.reason === "no_projection") && (
            <p className="text-sm text-destructive">
              No projection available this week (likely on bye or unmodeled):{" "}
              {lineup.unresolved_players
                .filter((p) => p.reason === "no_projection")
                .map((p) => p.player_id)
                .join(", ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
