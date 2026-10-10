import { DitherPlate } from "@/components/dither/DitherPlate";
import type { MotifName } from "@/components/dither/motifs";
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
  breakdown: "bg-danger-soft border-danger border-t-danger",
  maintenance: "bg-warning-soft border-warning/60 border-t-warning",
};

// each machine wears a print of what it does: looms weave, frames spin cones, dye ranges roll cloth
const machineMotif = (code: string): MotifName => (code.startsWith("LM") ? "loom" : code.startsWith("DY") ? "rolls" : code.startsWith("SP") || code.startsWith("RF") ? "cones" : "gear");
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
        "dither-hover relative flex min-h-48 flex-col overflow-hidden border border-border border-t-2 border-t-foreground bg-card text-left outline-none focus-visible:ring-2 focus-visible:ring-ember",
        TILE_TINT[tile.status],
      )}
    >
      <span className="relative flex min-w-0 flex-1 flex-col gap-3.5 p-5">
        <span className="grid gap-1">
          <span className="flex items-center justify-between gap-2">
            <span className="figure text-[1.5rem] whitespace-nowrap">{tile.code}</span>
            <StatusBadge status={tile.status} className="shrink-0" />
          </span>
          <span className="label truncate normal-case tracking-[0.04em]">
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
            <span className="h-2.5 overflow-hidden border border-border bg-[radial-gradient(var(--input)_0.7px,transparent_1px)] bg-[size:4px_4px]" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100} aria-label={`${job.code} progress`}>
              <span className={cn("block h-full border-r-2 border-ember transition-[width] duration-500 ease-out", BAR[tile.status])} style={{ width: `${done}%` }} />
            </span>
            <span className="num text-[0.78rem] text-muted-foreground">
              {fmt(job.produced)} of {fmt(job.planned)} · {done}%
            </span>
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">{tile.queued ? `No job running · ${tile.queued} queued` : "No job"}</span>
        )}

        <span className="mt-auto flex items-end justify-between gap-2 border-t border-border pt-3">
          <span>
            <span className="label block">Made today</span>
            <span className="num text-lg font-medium">{fmt(tile.today_output)}</span>
          </span>
          <span className="min-w-0 truncate text-right text-[0.82rem] text-muted-foreground">{tile.crew.length ? tile.crew.join(", ") : "No crew"}</span>
        </span>
      </span>
      <DitherPlate motif={machineMotif(tile.code)} seed={tile.code} className="pointer-events-none !h-14 border-t border-border opacity-80 [mask-image:linear-gradient(to_right,transparent,#000_50%)]" />
    </button>
  );
}
