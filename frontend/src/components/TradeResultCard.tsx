import Avatar from "./Avatar";
import Card from "./Card";
import PlayerRow from "./PlayerRow";

export interface RosterPlayer {
  player_id: string;
  position: string;
  projected_points: number;
  name: string | null;
  team: string | null;
  injury_status: string | null;
}

export interface LineupImpact {
  before_total_projected_points: number;
  after_total_projected_points: number;
  change: number;
}

export interface TeamTradeResult {
  roster_id: number;
  giving_players: RosterPlayer[];
  receiving_players: RosterPlayer[];
  giving_total: number;
  receiving_total: number;
  differential: number;
  verdict: string;
  lineup_impact: LineupImpact;
  playoff_lineup_impact: LineupImpact | null;
}

// Fixed scan order so each column reads like a real roster page, not an
// arbitrary API-response order.
const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"];

function positionRank(position: string): number {
  const index = POSITION_ORDER.indexOf(position);
  return index === -1 ? POSITION_ORDER.length : index;
}

export function sortByPositionThenPoints(players: RosterPlayer[]): RosterPlayer[] {
  return [...players].sort((a, b) => {
    const rankDiff = positionRank(a.position) - positionRank(b.position);
    return rankDiff !== 0 ? rankDiff : b.projected_points - a.projected_points;
  });
}

function signed(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

/** One team's side of an evaluated trade -- verdict, pts/week, giving/
 * receiving breakdown, and the optional playoff-only breakdown. Shared by
 * Trade.tsx (one evaluated trade) and TradeFinder.tsx (one card per
 * participant per candidate) so this JSX exists in exactly one place. */
export default function TradeResultCard({
  team,
  teamLabel,
  numWeeks,
  playoffStartWeek,
  endWeek,
}: {
  team: TeamTradeResult;
  teamLabel: string;
  numWeeks: number;
  playoffStartWeek: number | null;
  endWeek: number;
}) {
  const perWeek = team.lineup_impact.change / numWeeks;
  return (
    <Card className="w-80 shrink-0">
      <div className="mb-2 flex items-center gap-2">
        <Avatar name={teamLabel} size={24} />
        <h3 className="font-semibold text-foreground">{teamLabel}</h3>
      </div>
      <p className="mb-0.5 font-semibold text-primary">{team.verdict}</p>
      <p className="mb-3 text-xs text-muted-foreground">
        ~{signed(perWeek)} pts/week for the rest of the season
      </p>
      <p className="mb-2 text-xs text-muted-foreground">
        Gives up {team.giving_total.toFixed(1)} pts of talent, gets back{" "}
        {team.receiving_total.toFixed(1)} — but a roster can only start so many players, so
        here's the real effect on the best lineup:
      </p>
      <p className="mb-1 text-xs text-muted-foreground">
        Weekly lineup: {team.lineup_impact.before_total_projected_points.toFixed(1)} →{" "}
        {team.lineup_impact.after_total_projected_points.toFixed(1)} pts (
        {signed(team.lineup_impact.change)})
      </p>
      {team.playoff_lineup_impact && playoffStartWeek != null && (
        <p className="mb-3 text-xs font-semibold text-primary">
          Your playoffs (weeks {playoffStartWeek}-{endWeek}): {signed(team.playoff_lineup_impact.change)}{" "}
          pts
        </p>
      )}
      {team.giving_players.length > 0 && (
        <>
          <p className="text-xs font-semibold text-muted-foreground">Sends</p>
          <ul>
            {sortByPositionThenPoints(team.giving_players).map((p) => (
              <PlayerRow
                key={p.player_id}
                playerId={p.player_id}
                position={p.position}
                name={p.name}
                team={p.team}
                points={p.projected_points}
              />
            ))}
          </ul>
        </>
      )}
      {team.receiving_players.length > 0 && (
        <>
          <p className="mt-2 text-xs font-semibold text-muted-foreground">Receives</p>
          <ul>
            {sortByPositionThenPoints(team.receiving_players).map((p) => (
              <PlayerRow
                key={p.player_id}
                playerId={p.player_id}
                position={p.position}
                name={p.name}
                team={p.team}
                points={p.projected_points}
              />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
