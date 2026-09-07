import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
    <div className="page">
      <h1>Which team is yours?</h1>
      {error && <p className="error">{error}</p>}
      {rosters === null && !error && <p>Loading...</p>}
      <ul>
        {rosters?.map((roster) => (
          <li key={roster.sleeper_roster_id}>
            <button
              type="button"
              disabled={claiming}
              onClick={() => claim(roster.sleeper_roster_id)}
            >
              {roster.owner_display_name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
