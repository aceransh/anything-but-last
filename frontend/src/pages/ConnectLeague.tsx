import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import Card from "@/components/Card";
import { Button } from "@/components/ui/button";
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
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <h1 className="mb-6 text-xl font-bold text-foreground">Connect a Sleeper League</h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            Sleeper League ID
            <input
              value={leagueId}
              onChange={(e) => setLeagueId(e.target.value)}
              required
              className="rounded-lg border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            />
          </label>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={submitting} className="w-full">
            Connect
          </Button>
        </form>
      </Card>
    </div>
  );
}
