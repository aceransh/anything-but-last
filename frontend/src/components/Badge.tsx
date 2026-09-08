import { cn } from "@/lib/utils";

const POSITION_COLORS: Record<string, string> = {
  QB: "bg-pos-qb/20 text-pos-qb",
  RB: "bg-pos-rb/20 text-pos-rb",
  WR: "bg-pos-wr/20 text-pos-wr",
  TE: "bg-pos-te/20 text-pos-te",
  K: "bg-pos-k/20 text-pos-k",
  DEF: "bg-pos-def/20 text-pos-def",
};

export function PositionBadge({ position }: { position: string }) {
  const colorClass = POSITION_COLORS[position] ?? "bg-pos-unknown/20 text-pos-unknown";
  return (
    <span
      className={cn(
        "inline-flex w-9 shrink-0 items-center justify-center rounded px-1 py-0.5 text-[0.65rem] font-bold tracking-wide",
        colorClass,
      )}
    >
      {position}
    </span>
  );
}

// Loud (destructive) for "likely/definitely not playing" statuses, passive
// (muted) for everything else (e.g. Questionable) -- same distinction the
// lineup optimizer's injury_warning flag already draws.
const LOUD_STATUSES = new Set(["Out", "Doubtful", "IR", "PUP", "Suspended"]);

export function InjuryBadge({ status, loud = false }: { status: string; loud?: boolean }) {
  const isLoud = loud || LOUD_STATUSES.has(status);
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[0.65rem] font-semibold",
        isLoud ? "bg-destructive/20 text-destructive" : "bg-muted text-muted-foreground",
      )}
    >
      {status}
    </span>
  );
}
