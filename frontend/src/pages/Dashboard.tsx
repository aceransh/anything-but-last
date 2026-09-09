import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Avatar from "@/components/Avatar";
import Card from "@/components/Card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "../lib/api";
import { supabase } from "../lib/supabaseClient";

interface League {
  id: string;
  sleeper_league_id: string;
  league_name: string;
  season: string;
  sleeper_roster_id: number | null;
}

export default function Dashboard() {
  const [leagues, setLeagues] = useState<League[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/leagues")
      .then((res) => res.json())
      .then(setLeagues)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load leagues"),
      );
  }, []);

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">Your Leagues</h1>
        <Button variant="outline" onClick={() => supabase.auth.signOut()}>
          Sign out
        </Button>
      </div>
      <Link to="/connect-league" className="text-sm text-primary underline-offset-4 hover:underline">
        Connect a league
      </Link>
      {error && <p className="mt-4 text-sm text-destructive">{error}</p>}
      {leagues === null && !error && <p className="mt-4 text-muted-foreground">Loading...</p>}
      {leagues?.length === 0 && <p className="mt-4 text-muted-foreground">No leagues connected yet.</p>}
      <ul className="mt-4 space-y-2">
        {leagues?.map((league) => (
          <li key={league.id}>
            <Link
              to={
                league.sleeper_roster_id === null
                  ? `/leagues/${league.id}/select-roster`
                  : `/leagues/${league.id}/matchup`
              }
            >
              <Card className="flex items-center gap-3 transition-colors hover:bg-secondary/60">
                <Avatar name={league.league_name} />
                <div>
                  <div className="font-medium text-foreground">{league.league_name}</div>
                  <div className="text-xs text-muted-foreground">{league.season}</div>
                </div>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
