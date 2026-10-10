"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, ClipboardCheck, ScanLine } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatStrip } from "@/components/layout/StatStrip";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Tabs } from "@/components/layout/Tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { duration, useNow } from "@/features/production/api";
import { dateTime, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";
import { cn } from "@/lib/utils";

import { type CheckFilters, type CheckRow, DEFECT_TYPES, type DefectGroup, defectLabel, findRoll, type QualitySummary, type RollRow, useChecks, useQueue, useSummary } from "./api";
import { RollInspection } from "./RollInspection";

const LIMIT = 25;
const PERIODS = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];
type Tab = "waiting" | "checked" | "analysis";

// long waits read in days: "3 d 04 h" instead of "76 h 00 m"
const waitedFor = (seconds: number) => {
  if (seconds < 86_400) return duration(seconds);
  const d = Math.floor(seconds / 86_400);
  return `${d} d ${String(Math.floor((seconds % 86_400) / 3600)).padStart(2, "0")} h`;
};

function SummaryStrip({ s }: { s: QualitySummary | undefined }) {
  if (!s) return <Skeleton className="mb-8 h-24 w-full" />;
  const all = s.all_attempts;
  const firsts = s.first_attempt.passed + s.first_attempt.rework + s.first_attempt.rejected;
  return (
    <StatStrip
      stats={[
        { key: "waiting", label: "Waiting now", value: s.waiting, sub: "rolls in the queue", tone: s.waiting ? "warn" : undefined },
        { key: "passed", label: "Passed", value: all.passed, sub: "every attempt", tone: "good" },
        { key: "rework", label: "Rework", value: all.rework, sub: "sent back to the floor" },
        { key: "rejected", label: "Rejected", value: all.rejected, sub: "moved to the reject bay", tone: all.rejected ? "bad" : undefined },
        { key: "rate", label: "First-pass yield", value: s.pass_rate_pct === null ? "—" : `${s.pass_rate_pct}%`, sub: `first attempt, ${firsts} rolls` },
      ]}
    />
  );
}

// scanner or keyboard: the roll code plus Enter opens that roll
function RollFinder() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function go(e: FormEvent) {
    e.preventDefault();
    const c = code.trim().toUpperCase();
    if (!c) return;
    setBusy(true);
    setError(undefined);
    try {
      const hit = (await findRoll(c)).items[0];
      if (hit) router.push(`/qc/rolls/${hit.id}`);
      else setError(`No roll with code ${c}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not look up the roll");
    } finally {
      setBusy(false);
      setCode("");
    }
  }

  return (
    <form onSubmit={go} role="search" className="mb-6 grid gap-2 border border-border bg-card p-4">
      <label htmlFor="roll-code" className="label">
        Scan or type a roll code
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <ScanLine className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input id="roll-code" autoComplete="off" placeholder="R-000123" value={code} onChange={(e) => setCode(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "roll-code-error" : undefined} className="h-12 pl-11 font-mono text-lg uppercase" />
        </div>
        <Button type="submit" className="h-12" disabled={busy || !code.trim()}>
          Open roll
        </Button>
      </div>
      {error && (
        <p id="roll-code-error" role="alert" className="text-sm font-medium text-danger">
          {error}
        </p>
      )}
    </form>
  );
}

const defectsText = (c: CheckRow) => (c.defects.length ? c.defects.map((d) => `${defectLabel(d.type)} ×${d.count}`).join(", ") : "None");

const CHECK_COLUMNS: Column<CheckRow>[] = [
  { key: "at", header: "Checked", cell: (c) => <span className="num">{dateTime(c.at)}</span> },
  {
    key: "roll",
    header: "Roll",
    cell: (c) => (
      <Link href={`/qc/rolls/${c.roll_id}`} className="num font-semibold hover:text-ember" onClick={(e) => e.stopPropagation()}>
        {c.roll_code}
      </Link>
    ),
  },
  { key: "order", header: "Order · loom", cell: (c) => <span className="num">{c.order_code} · {c.loom_code}</span> },
  { key: "decision", header: "Result", cell: (c) => <StatusBadge status={c.decision} /> },
  { key: "defects", header: "Defects", cell: (c) => <span className="block max-w-72 truncate" title={defectsText(c)}>{defectsText(c)}</span> },
  { key: "score", header: "Pts / 100 m²", className: "text-right", cell: (c) => <span className="num">{c.score ?? "—"}</span> },
  { key: "shade", header: "Shade", cell: (c) => c.shade_band ?? "—" },
  { key: "by", header: "Inspector", cell: (c) => c.inspector_name },
];

// every inspection, newest first; the result chips filter the list
function Checked({ filters, onFilters }: { filters: CheckFilters; onFilters: (f: CheckFilters) => void }) {
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const checks = useChecks(filters, offset, LIMIT);
  const set = (f: CheckFilters) => {
    onFilters(f);
    setOffset(0);
  };
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2" role="radiogroup" aria-label="Result">
        {(["", "pass", "rework", "reject"] as const).map((d) => {
          const on = (filters.decision ?? "") === d;
          return (
            <Button key={d || "all"} size="sm" role="radio" aria-checked={on} variant={on ? "default" : "outline"} onClick={() => set({ decision: d || undefined })}>
              {d ? { pass: "Passed", rework: "Rework", reject: "Rejected" }[d] : "All results"}
            </Button>
          );
        })}
      </div>
      <DataTable
        columns={CHECK_COLUMNS}
        query={checks}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={(c) => router.push(`/qc/rolls/${c.roll_id}`)}
        empty={<EmptyState icon={ClipboardCheck} title="No checks match">Change the filter, or inspect a roll from the queue.</EmptyState>}
      />
    </>
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
function DefectLedger({ title, keyLabel, rows, days }: { title: string; keyLabel: string; rows: DefectGroup[] | undefined; days: number }) {
  const max = Math.max(1, ...(rows ?? []).map((r) => r.defects));
  return (
    <section className="border border-border border-t-foreground bg-card p-4">
      <h2 className="text-[1.45rem] font-normal">{title}</h2>
      <p className="label mt-1">Last {days} {days === 1 ? "day" : "days"} · top 10</p>
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
          <dt className="label">{defectLabel(t)}</dt>
          <dd className="num mt-1 text-[1.3rem]">{s.defects_by_type[t] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}

// R12 + R13: the QC queue, what was decided, and where the defects come from
export function QcPage() {
  useSSE(["quality"]);
  const [days, setDays] = useState(7);
  const [tab, setTab] = useState<Tab>("waiting");
  const [filters, setFilters] = useState<CheckFilters>({});
  const summary = useSummary(days);
  const [open, setOpen] = useState<RollRow | null>(null);

  return (
    <>
      <PageHeader
        title="QC queue"
        description="Inspect each roll: pass with a shade band, send back for rework, or reject. Updates live."
        actions={
          <div className="flex border border-foreground" role="radiogroup" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.days} type="button" role="radio" aria-checked={days === p.days} onClick={() => setDays(p.days)} className={cn("pressable h-10 px-4 text-[0.88rem] font-medium", days === p.days ? "bg-primary text-primary-foreground" : "bg-background hover:bg-accent")}>
                {p.label}
              </button>
            ))}
          </div>
        }
      />

      <RollFinder />
      {summary.isError ? (
        <p role="alert" className="mb-8 border border-danger bg-danger-soft px-3 py-2.5 text-sm text-danger">
          Summary did not load: {summary.error.message}
        </p>
      ) : (
        <SummaryStrip s={summary.data} />
      )}

      <Tabs
        label="Quality views"
        value={tab}
        onChange={setTab}
        items={[
          { key: "waiting", label: "Waiting", count: summary.data?.waiting },
          { key: "checked", label: "Checked" },
          { key: "analysis", label: "Defect analysis" },
        ]}
      />
      {tab === "waiting" && <Queue onOpen={setOpen} />}
      {tab === "checked" && <Checked filters={filters} onFilters={setFilters} />}
      {tab === "analysis" && (
        <div className="grid gap-4">
          <DefectTypes s={summary.data} />
          <div className="grid gap-4 lg:grid-cols-2">
            <DefectLedger title="Defects by loom" keyLabel="Loom" rows={summary.data?.by_machine} days={days} />
            <DefectLedger title="Defects by order" keyLabel="Order" rows={summary.data?.by_order} days={days} />
          </div>
        </div>
      )}

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
