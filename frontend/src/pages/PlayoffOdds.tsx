import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Avatar from "@/components/Avatar";
import Card from "@/components/Card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { apiFetch } from "../lib/api";

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

export default function PlayoffOdds() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [ownRosterId, setOwnRosterId] = useState<number | null | undefined>(undefined);
  const [rosters, setRosters] = useState<RosterOption[] | null>(null);
  const [source, setSource] = useState<Source>("sleeper");
  const [odds, setOdds] = useState<PlayoffOddsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      .catch(() => setRosters([]));
  }, [leagueId]);

  useEffect(() => {
    if (ownRosterId == null) return;
    setError(null);
    setLoading(true);
    apiFetch(`/leagues/${leagueId}/playoff-odds?source=${source}`)
      .then((res) => res.json())
      .then(setOdds)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load playoff odds"))
      .finally(() => setLoading(false));
  }, [leagueId, ownRosterId, source]);

  const nameByRosterId = new Map(rosters?.map((r) => [r.sleeper_roster_id, r.owner_display_name]));
  function teamLabel(rosterId: number): string {
    return rosterId === ownRosterId ? "You" : nameByRosterId.get(rosterId) ?? String(rosterId);
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="mb-1 text-xl font-bold text-foreground">Playoff Odds</h1>
          <p className="text-sm text-muted-foreground">
            Monte Carlo simulation of the rest of the real remaining schedule, assuming each team plays
            its optimal lineup every week.
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

      {error && <p className="text-sm text-destructive">{error}</p>}
      {ownRosterId === null && (
        <p className="text-sm text-destructive">
          No roster claimed for this league yet -- claim your team first.
        </p>
      )}

      {ownRosterId != null && (
        <section>
          {loading && (
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
