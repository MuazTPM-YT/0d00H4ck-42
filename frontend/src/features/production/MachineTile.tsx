import { Activity, CirclePause, Clock, type LucideIcon, Pause, Power, TriangleAlert, Wrench } from "lucide-react";

import { DitherPlate } from "@/components/dither/DitherPlate";
import type { MotifName } from "@/components/dither/motifs";
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

// state as one icon in a square, coloured by meaning; the word lives in the tooltip and for
// screen readers, so a long status can never push the card out of shape
const STATE: Record<MachineStatus, { icon: LucideIcon; tone: string }> = {
  running: { icon: Activity, tone: "border-info/40 bg-info-soft text-info" },
  idle: { icon: Pause, tone: "border-neutral/30 bg-neutral-soft text-neutral" },
  breakdown: { icon: TriangleAlert, tone: "border-danger/50 bg-danger text-white" },
  maintenance: { icon: Wrench, tone: "border-warning/50 bg-warning-soft text-warning" },
  off: { icon: Power, tone: "border-neutral/30 bg-neutral-soft text-neutral" },
};

function StateIcon({ status }: { status: MachineStatus }) {
  const { icon: Icon, tone } = STATE[status];
  return (
    <span className={cn("grid size-9 shrink-0 place-items-center border", tone)} title={humanize(status)}>
      <Icon className="size-[1.1rem]" strokeWidth={2.2} aria-hidden />
      <span className="sr-only">{humanize(status)}</span>
    </span>
  );
}

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
        "dither-hover relative flex min-h-48 min-w-0 flex-col overflow-hidden border border-border border-t-2 border-t-foreground bg-card text-left outline-none focus-visible:ring-2 focus-visible:ring-ember",
        TILE_TINT[tile.status],
      )}
    >
      <span className="relative flex min-w-0 flex-1 flex-col gap-3.5 p-5">
        <span className="flex min-w-0 items-start justify-between gap-3">
          <span className="grid min-w-0 gap-1">
            <span className="figure truncate text-[1.5rem]">{tile.code}</span>
            <span className="label truncate normal-case tracking-[0.04em]">{tile.name}</span>
            {since && (
              <span className="num flex min-w-0 items-center gap-1.5 text-[0.75rem] text-muted-foreground">
                <Clock className="size-3.5 shrink-0" aria-hidden />
                <span className="truncate">
                  {humanize(tile.status)} {since}
                </span>
              </span>
            )}
          </span>
          <StateIcon status={tile.status} />
        </span>

        {tile.reason && tile.status !== "running" && <span className={cn("line-clamp-2 text-[0.9rem] font-medium", tile.status === "maintenance" ? "text-warning" : "text-danger")}>{tile.reason}</span>}

        {job ? (
          <span className="grid min-w-0 gap-1.5">
            <span className="flex min-w-0 items-center justify-between gap-2 text-[0.94rem]">
              <span className="min-w-0 truncate font-semibold" title={`${job.order_code} · ${job.code}${job.roll_id ? " · rework" : ""}`}>
                {job.order_code} · {job.code}
                {job.roll_id && " · rework"}
              </span>
              {job.status === "paused" && (
                <span className="shrink-0 text-warning" title="Job paused">
                  <CirclePause className="size-5" aria-hidden />
                  <span className="sr-only">Job paused</span>
                </span>
              )}
            </span>
            <span className="h-2.5 overflow-hidden border border-border bg-[radial-gradient(var(--input)_0.7px,transparent_1px)] bg-[size:4px_4px]" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100} aria-label={`${job.code} progress`}>
              <span className={cn("block h-full border-r-2 border-ember transition-[width] duration-500 ease-out", BAR[tile.status])} style={{ width: `${done}%` }} />
            </span>
            <span className="num flex min-w-0 items-baseline justify-between gap-2 text-[0.78rem] text-muted-foreground">
              <span className="min-w-0 truncate">
                {fmt(job.produced)} / {fmt(job.planned)}
              </span>
              <span className="shrink-0 font-medium text-foreground">{done}%</span>
            </span>
          </span>
        ) : (
          <span className="truncate text-sm text-muted-foreground">{tile.queued ? `No job running · ${tile.queued} queued` : "No job"}</span>
        )}

        <span className="mt-auto flex items-end justify-between gap-2 border-t border-border pt-3">
          <span className="min-w-0">
            <span className="label block">Made today</span>
            <span className="num block truncate text-lg font-medium">{fmt(tile.today_output)}</span>
          </span>
          <span className="min-w-0 shrink truncate text-right text-[0.82rem] text-muted-foreground" title={tile.crew.join(", ")}>{tile.crew.length ? tile.crew.join(", ") : "No crew"}</span>
        </span>
      </span>
      <DitherPlate motif={machineMotif(tile.code)} seed={tile.code} live={tile.status === "running"} className="pointer-events-none !h-14 border-t border-border opacity-80 [mask-image:linear-gradient(to_right,transparent,#000_50%)]" />
    </button>
  );
}
