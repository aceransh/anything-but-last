import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
    <div className="page">
      <div className="page-header">
        <h1>Your Leagues</h1>
        <button type="button" onClick={() => supabase.auth.signOut()}>
          Sign out
        </button>
      </div>
      <Link to="/connect-league">Connect a league</Link>
      {error && <p className="error">{error}</p>}
      {leagues === null && !error && <p>Loading...</p>}
      {leagues?.length === 0 && <p>No leagues connected yet.</p>}
      <ul>
        {leagues?.map((league) => (
          <li key={league.id}>
            <Link
              to={
                league.sleeper_roster_id === null
                  ? `/leagues/${league.id}/select-roster`
                  : `/leagues/${league.id}/lineup`
              }
            >
              {league.league_name} ({league.season})
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
