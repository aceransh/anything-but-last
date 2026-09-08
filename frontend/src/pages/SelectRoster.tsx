import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Avatar from "@/components/Avatar";
import Card from "@/components/Card";
import { apiFetch } from "../lib/api";

interface RosterOption {
  sleeper_roster_id: number;
  owner_display_name: string;
}

export default function SelectRoster() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const navigate = useNavigate();
  const [rosters, setRosters] = useState<RosterOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);

  useEffect(() => {
    apiFetch(`/leagues/${leagueId}/rosters`)
      .then((res) => res.json())
      .then(setRosters)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load rosters"),
      );
  }, [leagueId]);

  async function claim(sleeperRosterId: number) {
    setError(null);
    setClaiming(true);
    try {
      await apiFetch(`/leagues/${leagueId}`, {
        method: "PATCH",
        body: JSON.stringify({ sleeper_roster_id: sleeperRosterId }),
      });
      navigate(`/leagues/${leagueId}/lineup`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to claim roster");
      setClaiming(false);
    }
  }

  return (
    <div className="mx-auto max-w-md px-4 py-12">
      <h1 className="mb-6 text-xl font-bold text-foreground">Which team is yours?</h1>
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
      {rosters === null && !error && <p className="text-muted-foreground">Loading...</p>}
      <ul className="space-y-2">
        {rosters?.map((roster) => (
          <li key={roster.sleeper_roster_id}>
            <button
              type="button"
              disabled={claiming}
              onClick={() => claim(roster.sleeper_roster_id)}
              className="w-full disabled:opacity-50"
            >
              <Card className="flex items-center gap-3 transition-colors hover:bg-secondary/60">
                <Avatar name={roster.owner_display_name} />
                <span className="font-medium text-foreground">{roster.owner_display_name}</span>
              </Card>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
