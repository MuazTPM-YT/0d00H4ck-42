"use client";

import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { humanize, kg, metres } from "@/lib/format";

import { type BoardTile, duration, MACHINE_STATUSES, todayIST, useTimeline } from "./api";
import { OutputForm, ProcessRollForm, RollForm, StatusForm } from "./FloorForms";
import { STATUS_BAR } from "./MachineTile";

const time = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" });

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-3 border-t pt-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

// today for one machine: time split by status, every event, and the supervisor's actions
export function MachinePanel({ tile, onClose }: { tile: BoardTile | null; onClose: () => void }) {
  const timeline = useTimeline(tile?.machine_id ?? null, todayIST());
  const fmt = tile?.unit === "kg" ? kg : metres;
  const seconds = timeline.data?.seconds ?? {};
  const total = Object.values(seconds).reduce((a, b) => a + (b ?? 0), 0);
  const job = tile?.job;

  return (
    <Sheet open={tile !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {tile && (
          <div className="grid gap-4 px-4 pb-6">
            <SheetHeader className="px-0">
              <SheetTitle className="flex items-center gap-2">
                {tile.code} <StatusBadge status={tile.status} />
              </SheetTitle>
              <SheetDescription>
                {tile.name}
                {tile.reason && ` · ${tile.reason}`}
              </SheetDescription>
            </SheetHeader>

            <Section title="Today">
              {timeline.isPending ? (
                <Skeleton className="h-16 w-full" />
              ) : timeline.isError ? (
                <EmptyState icon={AlertTriangle} title="Could not load today" action={<Button variant="outline" onClick={() => timeline.refetch()}>Try again</Button>}>
                  {timeline.error.message}
                </EmptyState>
              ) : (
                <>
                  <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label="Time split by status today">
                    {MACHINE_STATUSES.map((s) =>
                      seconds[s] ? <div key={s} className={STATUS_BAR[s]} style={{ width: `${(seconds[s]! / total) * 100}%` }} /> : null,
                    )}
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
                    {MACHINE_STATUSES.filter((s) => seconds[s]).map((s) => (
                      <div key={s} className="flex justify-between gap-2">
                        <dt className="text-muted-foreground">{humanize(s)}</dt>
                        <dd className="tabular">{duration(seconds[s]!)}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="text-sm">
                    Output today: <span className="font-semibold tabular">{fmt(timeline.data.total_output)}</span>
                  </p>
                  {timeline.data.events.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No status changes today.</p>
                  ) : (
                    <ol className="grid gap-1 text-sm">
                      {[...timeline.data.events].reverse().map((e) => (
                        <li key={e.id} className="flex items-baseline gap-2">
                          <span className="w-12 shrink-0 text-muted-foreground tabular">{time(e.at)}</span>
                          <StatusBadge status={e.status} />
                          <span className="min-w-0 truncate text-muted-foreground">{e.reason ?? (e.source === "machine" ? "machine feed" : "")}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              )}
            </Section>

            <Section title="Change status">
              <StatusForm key={tile.status} tile={tile} />
            </Section>

            {job && tile.status !== "breakdown" && tile.status !== "maintenance" && (
              <Section title={`${job.code} · ${job.order_code}`}>
                  {job.stage === "weaving" && !job.roll_id ? (
                    <>
                      <OutputForm tile={tile} />
                      <RollForm tile={tile} />
                    </>
                  ) : job.stage === "spinning" ? (
                    <OutputForm tile={tile} />
                  ) : (
                    <ProcessRollForm tile={tile} reworkRollId={job.roll_id} />
                  )}
              </Section>
            )}
            {!job && <p className="border-t pt-4 text-sm text-muted-foreground">No job on this machine. Queue one from Work orders.</p>}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
