import type { ReactNode } from "react";
import { InjuryBadge, PositionBadge } from "./Badge";

export default function PlayerRow({
  position,
  name,
  playerId,
  team,
  points,
  injuryStatus,
  injuryLoud = false,
  slot,
  note,
  right,
}: {
  position: string;
  name: string | null;
  playerId: string;
  team?: string | null;
  points?: number;
  injuryStatus?: string | null;
  injuryLoud?: boolean;
  slot?: string | null;
  note?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <li className="flex items-center gap-2 border-b border-border/60 py-2 text-sm last:border-b-0">
      {slot && <span className="w-10 shrink-0 text-xs text-muted-foreground">{slot}</span>}
      <PositionBadge position={position} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="truncate font-medium text-foreground">{name ?? playerId}</span>
          {team && <span className="text-xs text-muted-foreground">{team}</span>}
          {typeof points === "number" && (
            <span className="text-xs text-muted-foreground">{points.toFixed(1)} pts</span>
          )}
          {injuryStatus && <InjuryBadge status={injuryStatus} loud={injuryLoud} />}
        </div>
        {note && <div className="mt-0.5 text-xs text-amber-500">{note}</div>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </li>
  );
}
