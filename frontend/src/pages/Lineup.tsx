import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Card from "@/components/Card";
import PlayerRow from "@/components/PlayerRow";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "../lib/api";

type LineupSource = "sleeper" | "draftsharks";

const SOURCE_LABELS: Record<LineupSource, string> = {
  sleeper: "Sleeper",
  draftsharks: "DraftSharks",
};

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

interface ContextLineup {
  starters: LineupPlayer[];
  bench: LineupPlayer[];
  total_projected_points: number;
  w_context: number;
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
  context_lineup: ContextLineup | null;
}

type View = "optimal" | "destacked" | "context";

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
  const [source, setSource] = useState<LineupSource>("sleeper");
  const [winProb, setWinProb] = useState<number | null>(null);
  const [lineup, setLineup] = useState<LineupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("optimal");

  // Only needed to power the context-aware alternate below -- DraftSharks'
  // real floor/ceiling is what makes that meaningful (see CLAUDE.md).
  // A failed fetch (e.g. a bye week with no opponent) just means that
  // alternate won't be offered, not a page-level error.
  useEffect(() => {
    if (source !== "draftsharks") {
      setWinProb(null);
      return;
    }
    const query = week ? `?week=${week}&source=draftsharks` : "?source=draftsharks";
    apiFetch(`/leagues/${leagueId}/matchup${query}`)
      .then((res) => res.json())
      .then((data: { win_prob: number }) => setWinProb(data.win_prob))
      .catch(() => setWinProb(null));
  }, [leagueId, week, source]);

  useEffect(() => {
    setLineup(null);
    setError(null);
    setView("optimal");
    const params = new URLSearchParams({ source });
    if (week) params.set("week", String(week));
    if (source === "draftsharks" && winProb != null) {
      params.set("context_win_prob", String(winProb));
    }
    apiFetch(`/leagues/${leagueId}/lineup?${params}`)
      .then((res) => res.json())
      .then((data: LineupResponse) => {
        setLineup(data);
        setWeek(data.week);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load lineup"),
      );
  }, [leagueId, week, source, winProb]);

  const nameById = new Map(
    lineup ? lineup.starters.map((p) => [p.player_id, p.name ?? p.player_id]) : [],
  );

  const active =
    view === "destacked" && lineup?.alternate_lineup
      ? lineup.alternate_lineup
      : view === "context" && lineup?.context_lineup
        ? lineup.context_lineup
        : lineup;

  const contextLabel =
    lineup?.context_lineup && lineup.context_lineup.w_context >= 0.5
      ? "Boom-or-bust (you're the underdog)"
      : "Safe floor (protect your lead)";

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-xl font-bold text-foreground">Week {week ?? "..."} Lineup</h1>
        <Select value={source} onValueChange={(value) => setSource(value as LineupSource)}>
          <SelectTrigger size="sm" className="w-40 text-xs">
            <SelectValue>{SOURCE_LABELS[source]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sleeper">Sleeper</SelectItem>
            <SelectItem value="draftsharks">DraftSharks</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!lineup && !error && <p className="text-muted-foreground">Loading...</p>}
      {lineup && active && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">
              Projected total:{" "}
              <span className="font-semibold text-foreground">
                {active.total_projected_points.toFixed(1)} pts
              </span>
            </p>
            <div className="flex gap-2">
              {(lineup.alternate_lineup || lineup.context_lineup) && (
                <Button
                  variant={view === "optimal" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setView("optimal")}
                >
                  Optimal
                </Button>
              )}
              {lineup.alternate_lineup && (
                <Button
                  variant={view === "destacked" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setView("destacked")}
                >
                  De-stacked
                </Button>
              )}
              {lineup.context_lineup && (
                <Button
                  variant={view === "context" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setView("context")}
                >
                  {contextLabel}
                </Button>
              )}
            </div>
          </div>
          {view === "destacked" && lineup.alternate_lineup && (
            <p className="text-sm text-amber-500">
              Swaps out{" "}
              {lineup.alternate_lineup.swapped_out.map((id) => nameById.get(id) ?? id).join(", ")}{" "}
              for the cost of{" "}
              {(lineup.total_projected_points - lineup.alternate_lineup.total_projected_points).toFixed(1)}{" "}
              projected points.
            </p>
          )}
          {view === "context" && lineup.context_lineup && winProb != null && (
            <p className="text-sm text-amber-500">
              You're projected at ~{(winProb * 100).toFixed(0)}% to win this week -- this lineup{" "}
              {lineup.context_lineup.w_context >= 0.5
                ? "trades some expected points for more upside."
                : "leans toward the steadiest available options."}
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
