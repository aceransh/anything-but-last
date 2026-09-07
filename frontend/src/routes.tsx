import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./lib/AuthContext";
import ConnectLeague from "./pages/ConnectLeague";
import Dashboard from "./pages/Dashboard";
import Lineup from "./pages/Lineup";
import Login from "./pages/Login";
import SelectRoster from "./pages/SelectRoster";

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  if (loading) return <p>Loading...</p>;
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
        path="/leagues/:leagueId/lineup"
        element={
          <RequireAuth>
            <Lineup />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
