import { StatusBadge } from "@/components/layout/StatusBadge";
import { humanize, kg, metres } from "@/lib/format";
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

// a stopped machine tints its whole card, so it is found at a glance from across the floor
const TILE_TINT: Partial<Record<MachineStatus, string>> = {
  breakdown: "bg-danger-soft ring-2 ring-danger/40",
  maintenance: "bg-warning-soft ring-1 ring-warning/30",
};
const BAR: Record<MachineStatus, string> = { ...STATUS_BAR, idle: "bg-primary", off: "bg-primary" };

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
        "lift flex min-h-48 flex-col rounded-3xl bg-card text-left shadow-card outline-none focus-visible:ring-4 focus-visible:ring-ring/30",
        TILE_TINT[tile.status],
      )}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-3.5 p-5">
        <span className="grid gap-1">
          <span className="flex items-center justify-between gap-2">
            <span className="text-xl font-bold tracking-tight whitespace-nowrap">{tile.code}</span>
            <StatusBadge status={tile.status} className="shrink-0" />
          </span>
          <span className="truncate text-[0.82rem] text-muted-foreground tabular">
            {tile.name}
            {since && ` · ${humanize(tile.status)} for ${since}`}
          </span>
        </span>

        {tile.reason && tile.status !== "running" && <span className={cn("line-clamp-2 text-[0.9rem] font-medium", tile.status === "maintenance" ? "text-warning" : "text-danger")}>{tile.reason}</span>}

        {job ? (
          <span className="grid min-w-0 gap-1.5">
            <span className="flex items-center justify-between gap-2 text-[0.94rem]">
              <span className="min-w-0 truncate font-semibold">
                {job.order_code} · {job.code}
                {job.roll_id && " · rework"}
              </span>
              {job.status === "paused" && <StatusBadge status="paused" className="shrink-0" />}
            </span>
            <span className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100} aria-label={`${job.code} progress`}>
              <span className={cn("block h-full rounded-full transition-[width] duration-500 ease-out", BAR[tile.status])} style={{ width: `${done}%` }} />
            </span>
            <span className="text-[0.82rem] text-muted-foreground tabular">
              {fmt(job.produced)} of {fmt(job.planned)} · {done}%
            </span>
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">{tile.queued ? `No job running · ${tile.queued} queued` : "No job"}</span>
        )}

        <span className="mt-auto flex items-end justify-between gap-2 border-t border-border/70 pt-3">
          <span>
            <span className="block text-[0.78rem] text-muted-foreground">Made today</span>
            <span className="text-lg font-semibold tabular">{fmt(tile.today_output)}</span>
          </span>
          <span className="min-w-0 truncate text-right text-[0.82rem] text-muted-foreground">{tile.crew.length ? tile.crew.join(", ") : "No crew"}</span>
        </span>
      </span>
    </button>
  );
}
