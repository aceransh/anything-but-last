import { useEffect, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import { apiFetch } from "@/lib/api";
import { supabase } from "@/lib/supabaseClient";
import Avatar from "./Avatar";
import { cn } from "@/lib/utils";

interface League {
  id: string;
  league_name: string;
  season: string;
}

const TABS = [
  { to: "lineup", label: "Lineup" },
  { to: "trade", label: "Trade Evaluator" },
  { to: "trade-finder", label: "Trade Finder" },
  { to: "matchup-simulator", label: "Matchup Simulator" },
  { to: "waivers", label: "Waivers" },
];

export default function LeagueLayout() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const [leagues, setLeagues] = useState<League[] | null>(null);

  useEffect(() => {
    apiFetch("/leagues")
      .then((res) => res.json())
      .then(setLeagues)
      .catch(() => setLeagues([]));
  }, []);

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-card">
        <div className="border-b border-border px-4 py-4">
          <span className="text-lg font-bold text-primary">Fantasy Copilot</span>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <p className="px-2 pb-1 text-xs font-semibold tracking-wide text-muted-foreground">
            LEAGUES
          </p>
          <ul className="space-y-0.5">
            {leagues?.map((league) => (
              <li key={league.id}>
                <NavLink
                  to={`/leagues/${league.id}/lineup`}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm",
                    league.id === leagueId
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                  )}
                >
                  <Avatar name={league.league_name} size={24} />
                  <span className="truncate">{league.league_name}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="border-t border-border p-2">
          <button
            type="button"
            onClick={() => supabase.auth.signOut()}
            className="w-full rounded-lg px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex-1">
        <div className="flex gap-1 border-b border-border bg-card px-4">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={`/leagues/${leagueId}/${tab.to}`}
              className={({ isActive }) =>
                cn(
                  "border-b-2 px-3 py-3 text-sm font-medium",
                  isActive
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </div>
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
