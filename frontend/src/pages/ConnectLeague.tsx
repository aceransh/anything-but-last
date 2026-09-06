import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../lib/api";

export default function ConnectLeague() {
  const [leagueId, setLeagueId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await apiFetch("/leagues", {
        method: "POST",
        body: JSON.stringify({ sleeper_league_id: leagueId.trim() }),
      });
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <h1>Connect a Sleeper League</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Sleeper League ID
          <input
            value={leagueId}
            onChange={(e) => setLeagueId(e.target.value)}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={submitting}>
          Connect
        </button>
      </form>
    </div>
  );
}
