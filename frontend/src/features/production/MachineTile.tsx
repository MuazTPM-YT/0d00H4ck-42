import { StatusBadge } from "@/components/layout/StatusBadge";
import { kg, metres } from "@/lib/format";
import { cn } from "@/lib/utils";

import { type BoardTile, duration, type MachineStatus, pct } from "./api";

// same meaning as StatusBadge: blue moving, grey stopped, red broken, amber maintenance
export const STATUS_BAR: Record<MachineStatus, string> = {
  running: "bg-info",
  idle: "bg-neutral",
  breakdown: "bg-danger",
  maintenance: "bg-warning",
  off: "bg-neutral-soft",
};

export function MachineTile({ tile, now, onOpen }: { tile: BoardTile; now: number; onOpen: () => void }) {
  const fmt = tile.unit === "kg" ? kg : metres;
  const job = tile.job;
  const done = job ? pct(job.produced, job.planned) : 0;
  const since = tile.since ? duration((now - Date.parse(tile.since)) / 1000) : null;

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "flex min-h-44 flex-col overflow-hidden rounded-lg border bg-card text-left shadow-xs transition-shadow hover:shadow-md focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
        tile.status === "breakdown" && "border-danger",
      )}
    >
      <span className={cn("h-1.5 w-full", STATUS_BAR[tile.status])} aria-hidden />
      <span className="flex flex-1 flex-col gap-3 p-4">
        <span className="flex items-start justify-between gap-2">
          <span className="min-w-0">
            <span className="block text-lg font-semibold">{tile.code}</span>
            <span className="block truncate text-xs text-muted-foreground">{tile.name}</span>
          </span>
          <span className="flex flex-col items-end gap-1">
            <StatusBadge status={tile.status} />
            {since && <span className="text-xs text-muted-foreground tabular">{since}</span>}
          </span>
        </span>

        {tile.reason && tile.status !== "running" && <span className="line-clamp-2 text-sm text-danger">{tile.reason}</span>}

        {job ? (
          <span className="grid gap-1.5">
            <span className="flex justify-between gap-2 text-sm">
              <span className="truncate font-medium">
                {job.order_code} · {job.code}
                {job.roll_id && " · rework"}
              </span>
              {job.status === "paused" && <StatusBadge status="paused" />}
            </span>
            <span className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100} aria-label={`${job.code} progress`}>
              <span className="block h-full bg-primary" style={{ width: `${done}%` }} />
            </span>
            <span className="text-xs text-muted-foreground tabular">
              {fmt(job.produced)} of {fmt(job.planned)} · {done}%
            </span>
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">{tile.queued ? `No job running · ${tile.queued} queued` : "No job"}</span>
        )}

        <span className="mt-auto flex items-end justify-between gap-2 border-t pt-2 text-sm">
          <span>
            <span className="block text-xs text-muted-foreground">Today</span>
            <span className="font-semibold tabular">{fmt(tile.today_output)}</span>
          </span>
          <span className="min-w-0 truncate text-right text-xs text-muted-foreground">{tile.crew.length ? tile.crew.join(", ") : "No crew"}</span>
        </span>
      </span>
    </button>
  );
}
