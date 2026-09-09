import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Avatar from "@/components/Avatar";
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
import { apiFetch } from "@/lib/api";

type Source = "sleeper" | "draftsharks";

const SOURCE_LABELS: Record<Source, string> = {
  sleeper: "Sleeper",
  draftsharks: "DraftSharks",
};

interface League {
  id: string;
  sleeper_roster_id: number | null;
}

interface RosterOption {
  sleeper_roster_id: number;
  owner_display_name: string;
}

interface MatchupPlayer {
  player_id: string;
  position: string;
  projected_points: number;
  name: string | null;
  team: string | null;
  injury_status: string | null;
  slot: string | null;
}

interface ScoreStats {
  mean: number;
  median: number;
  p10: number;
  p90: number;
}

interface MatchupResponse {
  week: number;
  own_roster_id: number;
  opponent_roster_id: number;
  win_prob: number;
  opponent_win_prob: number;
  own_score: ScoreStats;
  opponent_score: ScoreStats;
  own_starters: MatchupPlayer[];
  opponent_starters: MatchupPlayer[];
}

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

type LineupView = "optimal" | "destacked" | "context";

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

function LineupPlayerList({
  players,
  nameById,
}: {
  players: LineupPlayer[];
  nameById: Map<string, string>;
}) {
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

export default function Matchup() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [ownRosterId, setOwnRosterId] = useState<number | null | undefined>(undefined);
  const [rosters, setRosters] = useState<RosterOption[] | null>(null);
  const [source, setSource] = useState<Source>("sleeper");

  const [matchup, setMatchup] = useState<MatchupResponse | null>(null);
  const [loadingMatchup, setLoadingMatchup] = useState(false);
  const [matchupError, setMatchupError] = useState<string | null>(null);

  const [lineup, setLineup] = useState<LineupResponse | null>(null);
  const [lineupError, setLineupError] = useState<string | null>(null);
  const [lineupView, setLineupView] = useState<LineupView>("optimal");

  useEffect(() => {
    apiFetch("/leagues")
      .then((res) => res.json())
      .then((leagues: League[]) => {
        const league = leagues.find((l) => l.id === leagueId);
        setOwnRosterId(league?.sleeper_roster_id ?? null);
      })
      .catch((err) => setMatchupError(err instanceof Error ? err.message : "Failed to load league"));

    apiFetch(`/leagues/${leagueId}/rosters`)
      .then((res) => res.json())
      .then(setRosters)
      .catch(() => setRosters([]));
  }, [leagueId]);

  useEffect(() => {
    if (ownRosterId == null) return;
    setMatchupError(null);
    setLoadingMatchup(true);
    apiFetch(`/leagues/${leagueId}/matchup?source=${source}`)
      .then((res) => res.json())
      .then(setMatchup)
      .catch((err) => setMatchupError(err instanceof Error ? err.message : "Failed to load this week's matchup"))
      .finally(() => setLoadingMatchup(false));
  }, [leagueId, ownRosterId, source]);

  useEffect(() => {
    if (ownRosterId == null) return;
    setLineup(null);
    setLineupError(null);
    setLineupView("optimal");
    const params = new URLSearchParams({ source });
    if (source === "draftsharks" && matchup?.win_prob != null) {
      params.set("context_win_prob", String(matchup.win_prob));
    }
    apiFetch(`/leagues/${leagueId}/lineup?${params}`)
      .then((res) => res.json())
      .then(setLineup)
      .catch((err) => setLineupError(err instanceof Error ? err.message : "Failed to load lineup"));
    // Only re-fetch when the win prob itself changes source/value, not on
    // every matchup poll -- avoids re-fetching the lineup recommendation
    // for reasons unrelated to it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueId, ownRosterId, source, matchup?.win_prob]);

  const nameByRosterId = new Map(rosters?.map((r) => [r.sleeper_roster_id, r.owner_display_name]));
  function teamLabel(rosterId: number): string {
    return rosterId === ownRosterId ? "You" : nameByRosterId.get(rosterId) ?? String(rosterId);
  }

  const lineupNameById = new Map(lineup ? lineup.starters.map((p) => [p.player_id, p.name ?? p.player_id]) : []);
  const activeLineup =
    lineupView === "destacked" && lineup?.alternate_lineup
      ? lineup.alternate_lineup
      : lineupView === "context" && lineup?.context_lineup
        ? lineup.context_lineup
        : lineup;
  const contextLabel =
    lineup?.context_lineup && lineup.context_lineup.w_context >= 0.5
      ? "Boom-or-bust (you're the underdog)"
      : "Safe floor (protect your lead)";

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="mb-1 text-xl font-bold text-foreground">Matchup</h1>
          <p className="text-sm text-muted-foreground">
            This week's real matchup (each side's actual set lineup) plus a lineup recommendation.
          </p>
        </div>
        <Select value={source} onValueChange={(value) => setSource(value as Source)}>
          <SelectTrigger size="sm" className="w-40 text-xs">
            <SelectValue>{SOURCE_LABELS[source]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sleeper">Sleeper</SelectItem>
            <SelectItem value="draftsharks">DraftSharks</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {ownRosterId === null && (
        <p className="text-sm text-destructive">
          No roster claimed for this league yet -- claim your team first.
        </p>
      )}

      {ownRosterId != null && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">This Week's Matchup</h2>
          {matchupError && <p className="text-sm text-destructive">{matchupError}</p>}
          {loadingMatchup && <p className="text-sm text-muted-foreground">Simulating...</p>}
          {!loadingMatchup && matchup && (
            <Card className="p-4">
              <div className="mb-4 flex items-center justify-between gap-4">
                <div className="flex flex-1 items-center gap-2">
                  <Avatar name={teamLabel(matchup.own_roster_id)} size={28} />
                  <div>
                    <p className="font-semibold text-foreground">{teamLabel(matchup.own_roster_id)}</p>
                    <p className="text-xs text-muted-foreground">
                      {matchup.own_score.mean.toFixed(1)} pts avg
                    </p>
                  </div>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">Week {matchup.week}</span>
                <div className="flex flex-1 items-center justify-end gap-2 text-right">
                  <div>
                    <p className="font-semibold text-foreground">
                      {teamLabel(matchup.opponent_roster_id)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {matchup.opponent_score.mean.toFixed(1)} pts avg
                    </p>
                  </div>
                  <Avatar name={teamLabel(matchup.opponent_roster_id)} size={28} />
                </div>
              </div>

              <div className="mb-1 flex justify-between text-xs font-semibold text-muted-foreground">
                <span>{pct(matchup.win_prob)} win</span>
                <span>{pct(matchup.opponent_win_prob)} win</span>
              </div>
              <div className="mb-4 flex h-2 overflow-hidden rounded-full bg-secondary">
                <div className="bg-primary" style={{ width: `${matchup.win_prob * 100}%` }} />
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs text-muted-foreground">
                <p>
                  Likely range: {matchup.own_score.p10.toFixed(0)}-{matchup.own_score.p90.toFixed(0)} pts
                </p>
                <p className="text-right">
                  Likely range: {matchup.opponent_score.p10.toFixed(0)}-{matchup.opponent_score.p90.toFixed(0)} pts
                </p>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-4">
                <ul>
                  {matchup.own_starters.map((p) => (
                    <PlayerRow
                      key={p.player_id}
                      playerId={p.player_id}
                      position={p.position}
                      name={p.name}
                      team={p.team}
                      points={p.projected_points}
                      injuryStatus={p.injury_status}
                      slot={p.slot}
                    />
                  ))}
                </ul>
                <ul>
                  {matchup.opponent_starters.map((p) => (
                    <PlayerRow
                      key={p.player_id}
                      playerId={p.player_id}
                      position={p.position}
                      name={p.name}
                      team={p.team}
                      points={p.projected_points}
                      injuryStatus={p.injury_status}
                      slot={p.slot}
                    />
                  ))}
                </ul>
              </div>
            </Card>
          )}
        </section>
      )}

      {ownRosterId != null && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
            {lineup ? `Week ${lineup.week} Lineup Recommendation` : "Lineup Recommendation"}
          </h2>
          {lineupError && <p className="text-sm text-destructive">{lineupError}</p>}
          {!lineup && !lineupError && <p className="text-sm text-muted-foreground">Loading...</p>}
          {lineup && activeLineup && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">
                  Projected total:{" "}
                  <span className="font-semibold text-foreground">
                    {activeLineup.total_projected_points.toFixed(1)} pts
                  </span>
                </p>
                <div className="flex gap-2">
                  {(lineup.alternate_lineup || lineup.context_lineup) && (
                    <Button
                      variant={lineupView === "optimal" ? "default" : "outline"}
                      size="sm"
                      onClick={() => setLineupView("optimal")}
                    >
                      Optimal
                    </Button>
                  )}
                  {lineup.alternate_lineup && (
                    <Button
                      variant={lineupView === "destacked" ? "default" : "outline"}
                      size="sm"
                      onClick={() => setLineupView("destacked")}
                    >
                      De-stacked
                    </Button>
                  )}
                  {lineup.context_lineup && (
                    <Button
                      variant={lineupView === "context" ? "default" : "outline"}
                      size="sm"
                      onClick={() => setLineupView("context")}
                    >
                      {contextLabel}
                    </Button>
                  )}
                </div>
              </div>
              {lineupView === "destacked" && lineup.alternate_lineup && (
                <p className="text-sm text-amber-500">
                  Swaps out{" "}
                  {lineup.alternate_lineup.swapped_out.map((id) => lineupNameById.get(id) ?? id).join(", ")}{" "}
                  for the cost of{" "}
                  {(lineup.total_projected_points - lineup.alternate_lineup.total_projected_points).toFixed(1)}{" "}
                  projected points.
                </p>
              )}
              {lineupView === "context" && lineup.context_lineup && matchup?.win_prob != null && (
                <p className="text-sm text-amber-500">
                  You're projected at ~{(matchup.win_prob * 100).toFixed(0)}% to win this week -- this lineup{" "}
                  {lineup.context_lineup.w_context >= 0.5
                    ? "trades some expected points for more upside."
                    : "leans toward the steadiest available options."}
                </p>
              )}

              <Card>
                <h3 className="mb-2 text-sm font-semibold text-muted-foreground">Starters</h3>
                <LineupPlayerList players={activeLineup.starters} nameById={lineupNameById} />
              </Card>

              <Card>
                <h3 className="mb-2 text-sm font-semibold text-muted-foreground">Bench</h3>
                <LineupPlayerList players={activeLineup.bench} nameById={lineupNameById} />
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
        </section>
      )}
    </div>
  );
}
