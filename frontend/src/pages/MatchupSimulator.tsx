import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Avatar from "@/components/Avatar";
import Card from "@/components/Card";
import PlayerRow from "@/components/PlayerRow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { apiFetch } from "../lib/api";

type MatchupSource = "sleeper" | "draftsharks";

const SOURCE_LABELS: Record<MatchupSource, string> = {
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

interface PlayoffOddsEntry {
  roster_id: number;
  current_wins: number;
  current_losses: number;
  current_ties: number;
  current_fpts: number;
  playoff_odds: number;
}

interface PlayoffOddsResponse {
  playoff_teams: number;
  playoff_week_start: number | null;
  entries: PlayoffOddsEntry[];
}

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

export default function MatchupSimulator() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [ownRosterId, setOwnRosterId] = useState<number | null | undefined>(undefined);
  const [rosters, setRosters] = useState<RosterOption[] | null>(null);
  const [source, setSource] = useState<MatchupSource>("sleeper");
  const [matchup, setMatchup] = useState<MatchupResponse | null>(null);
  const [loadingMatchup, setLoadingMatchup] = useState(false);
  const [odds, setOdds] = useState<PlayoffOddsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [oddsError, setOddsError] = useState<string | null>(null);
  const [loadingOdds, setLoadingOdds] = useState(false);

  useEffect(() => {
    apiFetch("/leagues")
      .then((res) => res.json())
      .then((leagues: League[]) => {
        const league = leagues.find((l) => l.id === leagueId);
        setOwnRosterId(league?.sleeper_roster_id ?? null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load league"));

    apiFetch(`/leagues/${leagueId}/rosters`)
      .then((res) => res.json())
      .then(setRosters)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load rosters"));
  }, [leagueId]);

  useEffect(() => {
    if (ownRosterId == null) return;
    setError(null);
    setLoadingMatchup(true);
    apiFetch(`/leagues/${leagueId}/matchup?source=${source}`)
      .then((res) => res.json())
      .then(setMatchup)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load this week's matchup"))
      .finally(() => setLoadingMatchup(false));
  }, [leagueId, ownRosterId, source]);

  useEffect(() => {
    if (ownRosterId == null) return;
    setOddsError(null);
    setLoadingOdds(true);
    apiFetch(`/leagues/${leagueId}/playoff-odds?source=${source}`)
      .then((res) => res.json())
      .then(setOdds)
      .catch((err) => setOddsError(err instanceof Error ? err.message : "Failed to load playoff odds"))
      .finally(() => setLoadingOdds(false));
  }, [leagueId, ownRosterId, source]);

  const nameByRosterId = new Map(rosters?.map((r) => [r.sleeper_roster_id, r.owner_display_name]));

  function teamLabel(rosterId: number): string {
    return rosterId === ownRosterId ? "You" : nameByRosterId.get(rosterId) ?? String(rosterId);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="mb-1 text-xl font-bold text-foreground">Matchup Simulator</h1>
          <p className="text-sm text-muted-foreground">
            Correlated Monte Carlo simulation of real weekly score variance -- not a single point
            estimate.
          </p>
        </div>
        <Select value={source} onValueChange={(value) => setSource(value as MatchupSource)}>
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
      {ownRosterId === null && (
        <p className="text-sm text-destructive">
          No roster claimed for this league yet -- claim your team first.
        </p>
      )}

      {ownRosterId != null && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">This Week</h2>
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
            Rest-of-Season Playoff Odds
          </h2>
          {oddsError && <p className="text-sm text-destructive">{oddsError}</p>}
          {loadingOdds && (
            <p className="text-sm text-muted-foreground">
              {source === "draftsharks"
                ? "Fetching DraftSharks projections for every remaining week -- this can take longer than Sleeper..."
                : "Simulating the rest of the season..."}
            </p>
          )}
          {odds && (
            <Card className="overflow-hidden p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2 font-medium">Team</th>
                    <th className="px-4 py-2 font-medium">Record</th>
                    <th className="px-4 py-2 text-right font-medium">Playoff odds</th>
                  </tr>
                </thead>
                <tbody>
                  {odds.entries.map((entry) => (
                    <tr
                      key={entry.roster_id}
                      className={cn(
                        "border-b border-border/60 last:border-b-0",
                        entry.roster_id === ownRosterId && "bg-secondary/40",
                      )}
                    >
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <Avatar name={teamLabel(entry.roster_id)} size={20} />
                          <span className="font-medium text-foreground">
                            {teamLabel(entry.roster_id)}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {entry.current_wins}-{entry.current_losses}
                        {entry.current_ties > 0 ? `-${entry.current_ties}` : ""}
                      </td>
                      <td className="px-4 py-2 text-right font-semibold text-primary">
                        {pct(entry.playoff_odds)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </section>
      )}
    </div>
  );
}
