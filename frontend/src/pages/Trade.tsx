import { useEffect, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import Avatar from "@/components/Avatar";
import Card from "@/components/Card";
import PlayerRow from "@/components/PlayerRow";
import TradeResultCard, {
  type RosterPlayer,
  type TeamTradeResult,
  sortByPositionThenPoints,
} from "@/components/TradeResultCard";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { apiFetch } from "../lib/api";

interface League {
  id: string;
  sleeper_roster_id: number | null;
}

interface RosterOption {
  sleeper_roster_id: number;
  owner_display_name: string;
}

interface TradeEvaluateResponse {
  start_week: number;
  end_week: number;
  playoff_start_week: number | null;
  teams: TeamTradeResult[];
}

// State the Trade Finder page hands off via router state when the user
// picks "Open in builder" on a suggested trade -- pre-fills the team
// selection and per-player destinations and jumps straight to the
// assign-players step, instead of making them rebuild it by hand.
export interface TradePrefill {
  rosterIds: number[];
  destinations: Record<string, number>;
}

export default function Trade() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const location = useLocation();
  const prefill = (location.state as { prefill?: TradePrefill } | null)?.prefill;
  const [ownRosterId, setOwnRosterId] = useState<number | null | undefined>(undefined);
  const [rosters, setRosters] = useState<RosterOption[] | null>(null);
  const [step, setStep] = useState<"select-teams" | "assign-players">(
    prefill ? "assign-players" : "select-teams",
  );
  const [selectedRosterIds, setSelectedRosterIds] = useState<Set<number>>(
    () => new Set(prefill?.rosterIds ?? []),
  );
  const [rosterPlayers, setRosterPlayers] = useState<Record<number, RosterPlayer[] | null>>({});
  const [destinations, setDestinations] = useState<Record<string, number>>(
    prefill?.destinations ?? {},
  );
  const [result, setResult] = useState<TradeEvaluateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);

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

  // Load every roster's players up front, as soon as we know the league's
  // teams -- lets the user browse everyone's roster before picking who to
  // trade with, same as Sleeper's own "Propose Trade" screen.
  useEffect(() => {
    if (!rosters) return;
    for (const r of rosters) {
      const rosterId = r.sleeper_roster_id;
      if (rosterPlayers[rosterId]) continue;
      apiFetch(`/leagues/${leagueId}/trade/roster-players/${rosterId}`)
        .then((res) => res.json())
        .then((players: RosterPlayer[]) =>
          setRosterPlayers((prev) => ({ ...prev, [rosterId]: players })),
        )
        .catch((err) =>
          setError(err instanceof Error ? err.message : "Failed to load a roster"),
        );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rosters, leagueId]);

  const nameByRosterId = new Map(rosters?.map((r) => [r.sleeper_roster_id, r.owner_display_name]));

  function teamLabel(rosterId: number): string {
    return rosterId === ownRosterId ? "You" : nameByRosterId.get(rosterId) ?? String(rosterId);
  }

  function toggleTeam(rosterId: number) {
    if (rosterId === ownRosterId) return;
    const next = new Set(selectedRosterIds);
    if (next.has(rosterId)) next.delete(rosterId);
    else next.add(rosterId);
    setSelectedRosterIds(next);
  }

  function goToAssignPlayers() {
    setError(null);
    setResult(null);
    setDestinations({});
    setStep("assign-players");
  }

  function setDestination(playerId: string, toRosterId: number | null) {
    setDestinations((prev) => {
      const next = { ...prev };
      if (toRosterId === null) delete next[playerId];
      else next[playerId] = toRosterId;
      return next;
    });
  }

  async function handleEvaluate() {
    if (ownRosterId == null) return;
    const participantIds = [ownRosterId, ...selectedRosterIds];

    const ownerByPlayer: Record<string, number> = {};
    for (const rosterId of participantIds) {
      for (const player of rosterPlayers[rosterId] ?? []) {
        ownerByPlayer[player.player_id] = rosterId;
      }
    }
    const moves = Object.entries(destinations).map(([playerId, toRosterId]) => ({
      player_id: playerId,
      from_roster_id: ownerByPlayer[playerId],
      to_roster_id: toRosterId,
    }));

    setError(null);
    setEvaluating(true);
    try {
      const res = await apiFetch(`/leagues/${leagueId}/trade-evaluate`, {
        method: "POST",
        body: JSON.stringify({ roster_ids: participantIds, moves }),
      });
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to evaluate trade");
    } finally {
      setEvaluating(false);
    }
  }

  const participantIds = ownRosterId != null ? [ownRosterId, ...selectedRosterIds] : [];

  // Live, client-side-only preview of who sends/receives what, built purely
  // from already-fetched roster data + the destinations picked so far --
  // no network call, updates instantly as the user assigns players. Mirrors
  // Sleeper's own "Trade Summary" side panel.
  function liveSummaryFor(rosterId: number): { sends: RosterPlayer[]; receives: RosterPlayer[] } {
    const sends: RosterPlayer[] = [];
    const receives: RosterPlayer[] = [];
    for (const pid of participantIds) {
      for (const player of rosterPlayers[pid] ?? []) {
        const dest = destinations[player.player_id];
        if (dest === undefined) continue;
        if (pid === rosterId && dest !== rosterId) sends.push(player);
        if (dest === rosterId && pid !== rosterId) receives.push(player);
      }
    }
    return { sends, receives };
  }

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-4 text-xl font-bold text-foreground">Trade Evaluator</h1>
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
      {ownRosterId === null && (
        <p className="text-sm text-destructive">
          No roster claimed for this league yet -- claim your team first.
        </p>
      )}

      {ownRosterId != null && step === "select-teams" && (
        <div className="space-y-3">
          <h2 className="text-sm text-muted-foreground">
            Click a team to add them to the trade
          </h2>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {rosters?.map((r) => {
              const rosterId = r.sleeper_roster_id;
              const isOwn = rosterId === ownRosterId;
              const selected = isOwn || selectedRosterIds.has(rosterId);
              return (
                <Card
                  key={rosterId}
                  className={cn(
                    "w-56 shrink-0 p-3 transition-colors",
                    selected ? "border-primary" : "opacity-60 hover:opacity-100",
                  )}
                >
                  <button
                    type="button"
                    disabled={isOwn}
                    onClick={() => toggleTeam(rosterId)}
                    className="mb-2 flex w-full items-center gap-2 disabled:cursor-default"
                  >
                    <Avatar name={teamLabel(rosterId)} size={28} />
                    <span className="truncate text-sm font-semibold">{teamLabel(rosterId)}</span>
                  </button>
                  {!rosterPlayers[rosterId] ? (
                    <p className="text-xs text-muted-foreground">Loading...</p>
                  ) : (
                    <ul className="max-h-72 overflow-y-auto">
                      {sortByPositionThenPoints(rosterPlayers[rosterId]!).map((player) => (
                        <PlayerRow
                          key={player.player_id}
                          playerId={player.player_id}
                          position={player.position}
                          name={player.name}
                          team={player.team}
                        />
                      ))}
                    </ul>
                  )}
                </Card>
              );
            })}
          </div>
          <Button disabled={selectedRosterIds.size === 0} onClick={goToAssignPlayers}>
            Next
          </Button>
        </div>
      )}

      {ownRosterId != null && step === "assign-players" && (
        <div className="space-y-4">
          <Button variant="outline" size="sm" onClick={() => setStep("select-teams")}>
            &larr; Change teams
          </Button>
          <div className="flex gap-4">
            <div className="flex flex-1 gap-4 overflow-x-auto pb-2">
              {participantIds.map((rosterId) => (
                <Card key={rosterId} className="w-72 shrink-0">
                  <div className="mb-2 flex items-center gap-2">
                    <Avatar name={teamLabel(rosterId)} size={24} />
                    <h3 className="font-semibold text-foreground">{teamLabel(rosterId)}</h3>
                  </div>
                  {!rosterPlayers[rosterId] ? (
                    <p className="text-sm text-muted-foreground">Loading...</p>
                  ) : (
                    <ul className="max-h-[28rem] overflow-y-auto">
                      {sortByPositionThenPoints(rosterPlayers[rosterId]!).map((player) => (
                        <PlayerRow
                          key={player.player_id}
                          playerId={player.player_id}
                          position={player.position}
                          name={player.name}
                          team={player.team}
                          points={player.projected_points}
                          injuryStatus={player.injury_status}
                          right={
                            <Select
                              value={String(destinations[player.player_id] ?? "keep")}
                              onValueChange={(value) =>
                                setDestination(
                                  player.player_id,
                                  value === "keep" ? null : Number(value),
                                )
                              }
                            >
                              <SelectTrigger size="sm" className="text-xs">
                                <SelectValue>
                                  {(value: string) =>
                                    value === "keep" ? "Keep" : `Send to ${teamLabel(Number(value))}`
                                  }
                                </SelectValue>
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="keep">Keep</SelectItem>
                                {participantIds
                                  .filter((id) => id !== rosterId)
                                  .map((id) => (
                                    <SelectItem key={id} value={String(id)}>
                                      Send to {teamLabel(id)}
                                    </SelectItem>
                                  ))}
                              </SelectContent>
                            </Select>
                          }
                        />
                      ))}
                    </ul>
                  )}
                </Card>
              ))}
            </div>

            <div className="w-64 shrink-0 space-y-3">
              <h3 className="text-sm font-semibold text-muted-foreground">Trade Summary</h3>
              {participantIds.map((rosterId) => {
                const { sends, receives } = liveSummaryFor(rosterId);
                return (
                  <Card key={rosterId} className="p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <Avatar name={teamLabel(rosterId)} size={20} />
                      <span className="text-sm font-medium">{teamLabel(rosterId)}</span>
                    </div>
                    {sends.length === 0 && receives.length === 0 ? (
                      <p className="text-xs text-muted-foreground">No assets yet</p>
                    ) : (
                      <>
                        {receives.length > 0 && (
                          <div className="mb-1">
                            <p className="text-[0.65rem] font-semibold text-muted-foreground">
                              RECEIVES
                            </p>
                            {receives.map((p) => (
                              <p key={p.player_id} className="truncate text-xs">
                                {p.name ?? p.player_id}
                              </p>
                            ))}
                          </div>
                        )}
                        {sends.length > 0 && (
                          <div>
                            <p className="text-[0.65rem] font-semibold text-muted-foreground">
                              SENDS
                            </p>
                            {sends.map((p) => (
                              <p key={p.player_id} className="truncate text-xs">
                                {p.name ?? p.player_id}
                              </p>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </Card>
                );
              })}
            </div>
          </div>

          <Button
            disabled={evaluating || Object.keys(destinations).length === 0}
            onClick={handleEvaluate}
          >
            {evaluating ? "Evaluating..." : "Evaluate trade"}
          </Button>
        </div>
      )}

      {result && (
        <div className="mt-6 flex gap-4 overflow-x-auto pb-2">
          {result.teams.map((team) => (
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
      )}
    </div>
  );
}
