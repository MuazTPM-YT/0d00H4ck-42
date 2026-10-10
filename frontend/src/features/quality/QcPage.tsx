"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, ClipboardCheck } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { duration, useNow } from "@/features/production/api";
import { humanize, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";
import { cn } from "@/lib/utils";

import { DEFECT_TYPES, type DefectGroup, type QualitySummary, type RollRow, useQueue, useSummary } from "./api";
import { RollInspection } from "./RollInspection";

const LIMIT = 25;
const DAYS = 30;

// long waits read in days: "3 d 04 h" instead of "76 h 00 m"
const waitedFor = (seconds: number) => {
  if (seconds < 86_400) return duration(seconds);
  const d = Math.floor(seconds / 86_400);
  return `${d} d ${String(Math.floor((seconds % 86_400) / 3600)).padStart(2, "0")} h`;
};

// one ledger figure: mono label, big numeral, where it comes from
function Stat({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: "good" | "warn" | "bad" | "ember" }) {
  return (
    <section className="flex flex-col gap-3 border border-border border-t-foreground bg-card p-4">
      <span className="label">{label}</span>
      <p className={cn("figure text-[2.3rem]", tone === "good" && "text-success", tone === "warn" && "text-warning", tone === "bad" && "text-danger", tone === "ember" && "text-ember")}>
        {value}
      </p>
      <p className="text-sm text-body">{sub}</p>
    </section>
  );
}

function SummaryStrip({ s }: { s: QualitySummary | undefined }) {
  if (!s) return <Skeleton className="h-32 w-full" />;
  const all = s.all_attempts;
  const firsts = s.first_attempt.passed + s.first_attempt.rework + s.first_attempt.rejected;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Stat label="Waiting" value={String(s.waiting)} sub="Rolls in the queue now" tone={s.waiting ? "ember" : undefined} />
      <Stat label="Passed" value={String(all.passed)} sub={`Last ${s.days} days, every attempt`} tone="good" />
      <Stat label="Rework" value={String(all.rework)} sub="Sent back to the floor" tone="warn" />
      <Stat label="Rejected" value={String(all.rejected)} sub="Moved to the reject bay" tone="bad" />
      <Stat label="Pass rate" value={s.pass_rate_pct === null ? "—" : `${s.pass_rate_pct}%`} sub={`First attempt, ${firsts} rolls`} />
    </div>
  );
}

function Queue({ onOpen }: { onOpen: (row: RollRow) => void }) {
  const [offset, setOffset] = useState(0);
  const queue = useQueue(offset, LIMIT);
  const now = useNow();

  if (queue.isError) {
    return (
      <EmptyState icon={AlertTriangle} title="Could not load the queue" action={<Button variant="outline" onClick={() => queue.refetch()}>Try again</Button>}>
        {queue.error.message}
      </EmptyState>
    );
  }
  if (queue.data?.total === 0) {
    return (
      <EmptyState icon={ClipboardCheck} title="No rolls waiting">
        Rolls show up here when they come off their last stage. This list updates live.
      </EmptyState>
    );
  }
  const total = queue.data?.total ?? 0;
  return (
    <div className="border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Roll</TableHead>
            <TableHead>Order</TableHead>
            <TableHead className="hidden md:table-cell">Buyer</TableHead>
            <TableHead>Loom</TableHead>
            <TableHead className="hidden sm:table-cell">Shift</TableHead>
            <TableHead className="text-right">Length</TableHead>
            <TableHead className="text-right">Waiting</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {queue.isPending
            ? Array.from({ length: 5 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                </TableRow>
              ))
            : queue.data.items.map((r) => {
                const waited = Math.max(0, (now - new Date(r.waiting_since).getTime()) / 1000);
                return (
                  <TableRow
                    key={r.id}
                    tabIndex={0}
                    onClick={() => onOpen(r)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen(r))}
                    className="cursor-pointer outline-none focus-visible:bg-ember-soft"
                  >
                    <TableCell className="num font-medium">{r.code}</TableCell>
                    <TableCell className="num">{r.order_code}</TableCell>
                    <TableCell className="hidden max-w-48 truncate md:table-cell">{r.buyer_name}</TableCell>
                    <TableCell className="num">{r.loom_code}</TableCell>
                    <TableCell className="hidden sm:table-cell">{r.shift_name}</TableCell>
                    <TableCell className="num text-right">{metres(r.length_m)}</TableCell>
                    <TableCell className={cn("num text-right", waited > 4 * 3600 && "text-ember")}>{waitedFor(waited)}</TableCell>
                  </TableRow>
                );
              })}
        </TableBody>
      </Table>
      {total > LIMIT && (
        <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-2.5 text-[0.88rem] text-muted-foreground">
          <span className="num">{`${offset + 1}–${Math.min(offset + LIMIT, total)} of ${total}`}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
              <ChevronLeft />
            </Button>
            <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>
              <ChevronRight />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ledger rows with a hairline bar sized against the worst row
function DefectLedger({ title, keyLabel, rows }: { title: string; keyLabel: string; rows: DefectGroup[] | undefined }) {
  const max = Math.max(1, ...(rows ?? []).map((r) => r.defects));
  return (
    <section className="border border-border border-t-foreground bg-card p-4">
      <h2 className="text-[1.45rem] font-normal">{title}</h2>
      <p className="label mt-1">Last {DAYS} days · top 10</p>
      {!rows ? (
        <Skeleton className="mt-4 h-32 w-full" />
      ) : rows.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">No defects logged in this window.</p>
      ) : (
        <Table className="mt-3">
          <TableHeader>
            <TableRow>
              <TableHead>{keyLabel}</TableHead>
              <TableHead className="w-1/2" aria-hidden />
              <TableHead className="text-right">Defects</TableHead>
              <TableHead className="text-right">Checks</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.key}>
                <TableCell className="num">{r.key}</TableCell>
                <TableCell aria-hidden>
                  <div className="h-2 border border-border">
                    <div className="h-full bg-ember" style={{ width: `${(r.defects / max) * 100}%` }} />
                  </div>
                </TableCell>
                <TableCell className="num text-right">{r.defects}</TableCell>
                <TableCell className="num text-right text-muted-foreground">{r.checks}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function DefectTypes({ s }: { s: QualitySummary | undefined }) {
  if (!s) return null;
  return (
    <dl className="grid grid-cols-2 gap-px border border-border bg-border sm:grid-cols-4">
      {DEFECT_TYPES.map((t) => (
        <div key={t} className="bg-card px-4 py-3">
          <dt className="label">{humanize(t)}</dt>
          <dd className="num mt-1 text-[1.3rem]">{s.defects_by_type[t] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}

// R12 + R13: the QC queue, pass/fail over 30 days, and where the defects come from
export function QcPage() {
  useSSE(["quality"]);
  const summary = useSummary(DAYS);
  const [open, setOpen] = useState<RollRow | null>(null);

  return (
    <>
      <PageHeader title="QC queue" description="Inspect each roll: pass with a shade band, send back for rework, or reject. Updates live." />

      {summary.isError ? (
        <p role="alert" className="border border-danger bg-danger-soft px-3 py-2.5 text-sm text-danger">
          Summary did not load: {summary.error.message}
        </p>
      ) : (
        <SummaryStrip s={summary.data} />
      )}

      <section className="mt-8 grid gap-3">
        <h2 className="eyebrow">Waiting for inspection</h2>
        <Queue onOpen={setOpen} />
      </section>

      <section className="mt-10 grid gap-4">
        <h2 className="eyebrow">Defect analysis</h2>
        <DefectTypes s={summary.data} />
        <div className="grid gap-4 lg:grid-cols-2">
          <DefectLedger title="Defects by loom" keyLabel="Loom" rows={summary.data?.by_machine} />
          <DefectLedger title="Defects by order" keyLabel="Order" rows={summary.data?.by_order} />
        </div>
      </section>

      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full overflow-y-auto rounded-none sm:max-w-lg">
          {open && (
            <div className="grid gap-4 px-4 pb-8">
              <SheetHeader className="px-0">
                <SheetTitle>Inspect roll</SheetTitle>
                <SheetDescription>
                  {open.code} · {open.fabric_name}
                </SheetDescription>
              </SheetHeader>
              <RollInspection key={open.id} id={open.id} compact />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
