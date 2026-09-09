import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Avatar from "@/components/Avatar";
import Card from "@/components/Card";
import TradeResultCard, { type TeamTradeResult } from "@/components/TradeResultCard";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { TradePrefill } from "./Trade";

interface League {
  id: string;
  sleeper_roster_id: number | null;
}

interface RosterOption {
  sleeper_roster_id: number;
  owner_display_name: string;
}

interface TradeMove {
  player_id: string;
  from_roster_id: number;
  to_roster_id: number;
}

interface TradeCandidate {
  roster_ids: number[];
  moves: TradeMove[];
  teams: TeamTradeResult[];
}

interface TradeFinderResponse {
  start_week: number;
  end_week: number;
  playoff_start_week: number | null;
  candidates: TradeCandidate[];
}

export default function TradeFinder() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const navigate = useNavigate();
  const [ownRosterId, setOwnRosterId] = useState<number | null | undefined>(undefined);
  const [rosters, setRosters] = useState<RosterOption[] | null>(null);
  const [result, setResult] = useState<TradeFinderResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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

  const nameByRosterId = new Map(rosters?.map((r) => [r.sleeper_roster_id, r.owner_display_name]));

  function teamLabel(rosterId: number): string {
    return rosterId === ownRosterId ? "You" : nameByRosterId.get(rosterId) ?? String(rosterId);
  }

  async function handleFind() {
    setError(null);
    setLoading(true);
    try {
      const res = await apiFetch(`/leagues/${leagueId}/trade-finder`);
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to find trades");
    } finally {
      setLoading(false);
    }
  }

  function openInBuilder(candidate: TradeCandidate) {
    const destinations: Record<string, number> = {};
    for (const move of candidate.moves) destinations[move.player_id] = move.to_roster_id;
    const prefill: TradePrefill = {
      rosterIds: candidate.roster_ids.filter((id) => id !== ownRosterId),
      destinations,
    };
    navigate(`/leagues/${leagueId}/trade`, { state: { prefill } });
  }

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-1 text-xl font-bold text-foreground">Trade Finder</h1>
      <p className="mb-4 text-sm text-muted-foreground">
        Scans every roster in your league for 2-to-4-team trades (including 2-for-1 packages)
        that leave every participant's real starting lineup better off.
      </p>
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
      {ownRosterId === null && (
        <p className="text-sm text-destructive">
          No roster claimed for this league yet -- claim your team first.
        </p>
      )}

      {ownRosterId != null && (
        <Button disabled={loading} onClick={handleFind}>
          {loading ? "Scanning your league for trades..." : "Find trades for me"}
        </Button>
      )}

      {result && result.candidates.length === 0 && (
        <p className="mt-4 text-sm text-muted-foreground">
          No trades found right now where every team comes out ahead. Check back after rosters
          change, or build one yourself in the Trade Evaluator.
        </p>
      )}

      {result && result.candidates.length > 0 && (
        <div className="mt-6 space-y-6">
          {result.candidates.map((candidate, i) => (
            <Card key={i} className="p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {candidate.roster_ids.map((rosterId) => (
                    <div key={rosterId} className="flex items-center gap-1">
                      <Avatar name={teamLabel(rosterId)} size={20} />
                      <span className="text-sm font-medium">{teamLabel(rosterId)}</span>
                    </div>
                  ))}
                </div>
                <Button size="sm" variant="outline" onClick={() => openInBuilder(candidate)}>
                  Open in builder
                </Button>
              </div>
              <div className="flex gap-4 overflow-x-auto pb-2">
                {candidate.teams.map((team) => (
                  <TradeResultCard
                    key={team.roster_id}
                    team={team}
                    teamLabel={teamLabel(team.roster_id)}
                    numWeeks={result.end_week - result.start_week + 1}
                    playoffStartWeek={result.playoff_start_week}
                    endWeek={result.end_week}
                  />
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
