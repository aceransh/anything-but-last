import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Card from "@/components/Card";
import PlayerRow from "@/components/PlayerRow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "@/lib/api";

type WaiverSource = "sleeper" | "draftsharks";

const SOURCE_LABELS: Record<WaiverSource, string> = {
  sleeper: "Sleeper",
  draftsharks: "DraftSharks",
};

interface League {
  id: string;
  sleeper_roster_id: number | null;
  discord_webhook_url: string | null;
}

interface WaiverTarget {
  player_id: string;
  position: string;
  projected_points: number;
  name: string | null;
  team: string | null;
  injury_status: string | null;
  add_count: number;
  delta_v: number;
  roi_temporal: number;
  scarcity: number;
  competitor_multiplier: number;
  recommended_bid: number | null;
}

interface WaiverBoardResponse {
  week: number;
  is_faab_league: boolean;
  faab_total: number | null;
  faab_remaining: number | null;
  targets: WaiverTarget[];
}

interface WaiverAlert {
  id: string;
  sleeper_player_id: string;
  week: number;
  alerted_at: string;
  read_at: string | null;
  player_name: string | null;
  position: string | null;
  team: string | null;
}

export default function Waivers() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [ownRosterId, setOwnRosterId] = useState<number | null | undefined>(undefined);
  const [source, setSource] = useState<WaiverSource>("sleeper");
  const [board, setBoard] = useState<WaiverBoardResponse | null>(null);
  const [loadingBoard, setLoadingBoard] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [alerts, setAlerts] = useState<WaiverAlert[] | null>(null);
  const [showAlerts, setShowAlerts] = useState(false);

  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSaved, setWebhookSaved] = useState(false);
  const [savingWebhook, setSavingWebhook] = useState(false);

  useEffect(() => {
    apiFetch("/leagues")
      .then((res) => res.json())
      .then((leagues: League[]) => {
        const league = leagues.find((l) => l.id === leagueId);
        setOwnRosterId(league?.sleeper_roster_id ?? null);
        setWebhookUrl(league?.discord_webhook_url ?? "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load league"));

    apiFetch(`/leagues/${leagueId}/waiver-alerts`)
      .then((res) => res.json())
      .then(setAlerts)
      .catch(() => setAlerts([]));
  }, [leagueId]);

  useEffect(() => {
    if (ownRosterId == null) return;
    setError(null);
    setLoadingBoard(true);
    apiFetch(`/leagues/${leagueId}/waivers?source=${source}`)
      .then((res) => res.json())
      .then(setBoard)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load waiver targets"))
      .finally(() => setLoadingBoard(false));
  }, [leagueId, ownRosterId, source]);

  const unreadCount = alerts?.filter((a) => !a.read_at).length ?? 0;

  function markAlertsRead() {
    apiFetch(`/leagues/${leagueId}/waiver-alerts/mark-read`, { method: "POST" })
      .then(() =>
        setAlerts((prev) => prev?.map((a) => ({ ...a, read_at: a.read_at ?? new Date().toISOString() })) ?? null),
      )
      .catch(() => undefined);
  }

  function saveWebhook() {
    setSavingWebhook(true);
    setWebhookSaved(false);
    apiFetch(`/leagues/${leagueId}`, {
      method: "PATCH",
      body: JSON.stringify({ discord_webhook_url: webhookUrl.trim() || null }),
    })
      .then(() => setWebhookSaved(true))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to save webhook"))
      .finally(() => setSavingWebhook(false));
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="mb-1 text-xl font-bold text-foreground">Waivers</h1>
          <p className="text-sm text-muted-foreground">
            Trending free agents ranked by real marginal value to your lineup, with a suggested FAAB bid.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowAlerts((v) => !v)}
            className="relative rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            Alerts
            {unreadCount > 0 && (
              <span className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[0.6rem] font-bold text-white">
                {unreadCount}
              </span>
            )}
          </button>
          <Select value={source} onValueChange={(value) => setSource(value as WaiverSource)}>
            <SelectTrigger size="sm" className="w-40 text-xs">
              <SelectValue>{SOURCE_LABELS[source]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="sleeper">Sleeper</SelectItem>
              <SelectItem value="draftsharks">DraftSharks</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {showAlerts && (
        <Card>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground">Recent alerts</h2>
            {unreadCount > 0 && (
              <button type="button" onClick={markAlertsRead} className="text-xs text-primary hover:underline">
                Mark all read
              </button>
            )}
          </div>
          {alerts && alerts.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No alerts yet -- the hourly scan posts here when a trending free agent would actually help your
              lineup.
            </p>
          )}
          <ul>
            {alerts?.map((a) => (
              <PlayerRow
                key={a.id}
                playerId={a.sleeper_player_id}
                position={a.position ?? "?"}
                name={a.player_name}
                team={a.team}
                note={!a.read_at ? "New" : undefined}
              />
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <h2 className="mb-2 text-sm font-semibold text-muted-foreground">Discord alerts</h2>
        <p className="mb-3 text-xs text-muted-foreground">
          Paste a Discord incoming webhook URL to get pushed alerts (hourly scan) for trending free agents that
          would help this team. Leave blank to disable.
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={webhookUrl}
            onChange={(e) => {
              setWebhookUrl(e.target.value);
              setWebhookSaved(false);
            }}
            placeholder="https://discord.com/api/webhooks/..."
            className="flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-sm text-foreground"
          />
          <button
            type="button"
            onClick={saveWebhook}
            disabled={savingWebhook}
            className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {savingWebhook ? "Saving..." : "Save"}
          </button>
        </div>
        {webhookSaved && <p className="mt-2 text-xs text-primary">Saved.</p>}
      </Card>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {ownRosterId === null && (
        <p className="text-sm text-destructive">
          No roster claimed for this league yet -- claim your team first.
        </p>
      )}

      {ownRosterId != null && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground">
              {board ? `Week ${board.week} targets` : "Targets"}
            </h2>
            {board?.is_faab_league && (
              <span className="text-xs text-muted-foreground">
                FAAB remaining: <span className="font-semibold text-foreground">${board.faab_remaining}</span> / $
                {board.faab_total}
              </span>
            )}
          </div>

          {loadingBoard && <p className="text-sm text-muted-foreground">Ranking trending free agents...</p>}

          {!loadingBoard && board && !board.is_faab_league && (
            <p className="mb-3 text-xs text-muted-foreground">
              This league doesn't use FAAB budgets -- showing marginal-value ranking only.
            </p>
          )}

          {!loadingBoard && board && board.targets.length === 0 && (
            <p className="text-sm text-muted-foreground">No trending free agents right now.</p>
          )}

          {!loadingBoard && board && board.targets.length > 0 && (
            <Card className="p-0">
              <ul>
                {board.targets.map((t) => (
                  <PlayerRow
                    key={t.player_id}
                    playerId={t.player_id}
                    position={t.position}
                    name={t.name}
                    team={t.team}
                    points={t.projected_points}
                    injuryStatus={t.injury_status ?? undefined}
                    note={
                      t.delta_v > 0
                        ? `+${t.delta_v.toFixed(1)} pts to your lineup -- ${t.add_count.toLocaleString()} adds`
                        : `${t.add_count.toLocaleString()} adds, no lineup impact for you`
                    }
                    right={
                      t.recommended_bid !== null ? (
                        <span className="rounded bg-primary/20 px-2 py-1 text-xs font-bold text-primary">
                          ${t.recommended_bid} FAAB
                        </span>
                      ) : undefined
                    }
                  />
                ))}
              </ul>
            </Card>
          )}
        </section>
      )}
    </div>
  );
}
