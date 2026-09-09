import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import LeagueLayout from "./components/LeagueLayout";
import { useAuth } from "./lib/AuthContext";
import ConnectLeague from "./pages/ConnectLeague";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Matchup from "./pages/Matchup";
import PlayoffOdds from "./pages/PlayoffOdds";
import SelectRoster from "./pages/SelectRoster";
import Trade from "./pages/Trade";
import TradeFinder from "./pages/TradeFinder";
import Waivers from "./pages/Waivers";

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  if (loading) return <p className="p-6 text-muted-foreground">Loading...</p>;
  if (!session) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/connect-league"
        element={
          <RequireAuth>
            <ConnectLeague />
          </RequireAuth>
        }
      />
      <Route
        path="/leagues/:leagueId/select-roster"
        element={
          <RequireAuth>
            <SelectRoster />
          </RequireAuth>
        }
      />
      <Route
        path="/leagues/:leagueId"
        element={
          <RequireAuth>
            <LeagueLayout />
          </RequireAuth>
        }
      >
        <Route path="matchup" element={<Matchup />} />
        <Route path="trade" element={<Trade />} />
        <Route path="trade-finder" element={<TradeFinder />} />
        <Route path="playoff-odds" element={<PlayoffOdds />} />
        <Route path="waivers" element={<Waivers />} />
      </Route>
    </Routes>
  );
}
