"use client";

import { AlertTriangle, CheckCircle2, ChevronRight, ClipboardCheck, ScanLine } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatStrip } from "@/components/layout/StatStrip";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Tabs } from "@/components/layout/Tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { dateTime, metres } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSSE } from "@/lib/useSSE";
import { duration, useNow } from "@/features/production/api";

import { type Check, type CheckFilters, DECISION_LABEL, defectLabel, findRoll, type GroupRate, type Summary, useChecks, useQcSummary, useQueue } from "./api";

type Tab = "waiting" | "checked" | "analysis";
const PERIODS = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];
const LIMIT = 25;
const DECISIONS = ["", "pass", "rework", "reject"] as const;

export const defectsText = (c: Check) => (c.defects.length ? c.defects.map((d) => `${defectLabel(d.type)} ×${d.count}`).join(", ") : "None");

// scanner or keyboard: the code plus Enter opens that roll
function RollFinder() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function go(e: { preventDefault: () => void }) {
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
    <form onSubmit={go} className="grid gap-2" role="search">
      <label htmlFor="roll-code" className="label">
        Scan or type a roll code
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <ScanLine className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input id="roll-code" autoComplete="off" autoFocus placeholder="R-000123" value={code} onChange={(e) => setCode(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "roll-code-error" : undefined} className="h-12 pl-11 font-mono text-lg uppercase" />
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

function Strip({ s }: { s: Summary }) {
  return (
    <StatStrip
      stats={[
        { key: "waiting", label: "Waiting now", value: s.waiting, sub: metres(s.waiting_m), tone: s.waiting ? "warn" : undefined },
        { key: "in_rework", label: "In rework", value: s.in_rework, sub: "on the floor" },
        { key: "passed", label: "Passed", value: s.passed, sub: metres(s.passed_m), tone: "good" },
        { key: "rework", label: "Sent to rework", value: s.rework, sub: metres(s.rework_m) },
        { key: "rejected", label: "Rejected", value: s.rejected, sub: metres(s.rejected_m), tone: s.rejected ? "bad" : undefined },
        { key: "fpy", label: "First-pass yield", value: s.first_pass_yield_pct === null ? "—" : `${Number(s.first_pass_yield_pct).toFixed(1)}%`, sub: "passed at first check" },
      ]}
    />
  );
}

function Waiting() {
  const queue = useQueue();
  const now = useNow();
  if (queue.isError)
    return (
      <EmptyState icon={AlertTriangle} title="Could not load the queue" action={<Button variant="outline" onClick={() => queue.refetch()}>Try again</Button>}>
        {queue.error.message}
      </EmptyState>
    );
  if (queue.isPending) return <Skeleton className="h-72 w-full" />;
  if (queue.data.items.length === 0)
    return (
      <EmptyState icon={CheckCircle2} title="Nothing waiting">
        Every roll off the floor has been checked. New rolls appear here the moment they are cut.
      </EmptyState>
    );
  return (
    <div className="border border-border bg-card">
        <Table containerClassName="scroll-panel max-h-[34rem]">
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow>
              <TableHead>Roll</TableHead>
              <TableHead>Order</TableHead>
              <TableHead>Fabric</TableHead>
              <TableHead>Loom · shift</TableHead>
              <TableHead className="text-right">Length</TableHead>
              <TableHead className="text-right">Waiting</TableHead>
              <TableHead>
                <span className="sr-only">Open</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {queue.data.items.map((r) => {
              const waited = (now - Date.parse(r.ready_at)) / 1000;
              return (
                <TableRow key={r.id} className="relative">
                  <TableCell>
                    <Link href={`/qc/rolls/${r.id}`} className="num font-semibold after:absolute after:inset-0 hover:text-ember">
                      {r.code}
                    </Link>
                    {r.attempt_no > 1 && <span className="label ml-2 text-warning">Check {r.attempt_no}</span>}
                  </TableCell>
                  <TableCell>
                    <span className="block">{r.order_code}</span>
                    <span className="block text-[0.82rem] text-muted-foreground">{r.buyer_name}</span>
                  </TableCell>
                  <TableCell>
                    <span className="block">{r.fabric_name}</span>
                    <span className="block text-[0.82rem] text-muted-foreground">{r.colour}</span>
                  </TableCell>
                  <TableCell>
                    <span className="num block">{r.loom_code}</span>
                    <span className="block text-[0.82rem] text-muted-foreground">
                      Shift {r.shift_code}
                      {r.weaver_name ? ` · ${r.weaver_name}` : ""}
                    </span>
                  </TableCell>
                  <TableCell className="num text-right">{metres(r.length_m)}</TableCell>
                  <TableCell className={cn("num text-right", waited > 4 * 3600 && "font-semibold text-warning")}>{duration(waited)}</TableCell>
                  <TableCell className="w-10">
                    <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      <p className="border-t border-border px-4 py-2.5 text-[0.85rem] text-muted-foreground">
        {queue.data.total} rolls waiting · oldest first. Rows in amber have waited over 4 hours.
      </p>
    </div>
  );
}

const CHECK_COLUMNS: Column<Check>[] = [
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
  { key: "order", header: "Order · loom", cell: (c) => <span>{c.order_code} <span className="num text-muted-foreground">· {c.loom_code}</span></span> },
  { key: "decision", header: "Result", cell: (c) => <StatusBadge status={c.decision} /> },
  { key: "defects", header: "Defects", cell: (c) => <span className="block max-w-72 truncate" title={defectsText(c)}>{defectsText(c)}</span> },
  { key: "score", header: "Points / 100 m²", className: "text-right", cell: (c) => <span className="num">{c.score ?? "—"}</span> },
  { key: "shade", header: "Shade", cell: (c) => c.shade_band ?? "—" },
  { key: "by", header: "Inspector", cell: (c) => c.inspector_name },
];

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
      <div className="mb-4 flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Result">
        {DECISIONS.map((d) => (
          <Button key={d || "all"} size="sm" role="radio" aria-checked={(filters.decision ?? "") === d} variant={(filters.decision ?? "") === d ? "default" : "outline"} onClick={() => set({ ...filters, decision: d || undefined })}>
            {d ? DECISION_LABEL[d] : "All results"}
          </Button>
        ))}
        {(filters.machine_id || filters.order_id) && (
          <Button size="sm" variant="ghost" onClick={() => set({ decision: filters.decision })}>
            Clear loom / order filter
          </Button>
        )}
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

function RateTable({ title, rows, onPick, codeLabel }: { title: string; rows: GroupRate[]; onPick: (id: number) => void; codeLabel: string }) {
  return (
    <section className="border border-border bg-card">
      <h2 className="border-b border-border px-4 py-3 text-base">{title}</h2>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">No checks in this period.</p>
      ) : (
          <Table containerClassName="scroll-panel max-h-[26rem]">
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow>
                <TableHead>{codeLabel}</TableHead>
                <TableHead className="text-right">Checked</TableHead>
                <TableHead className="text-right">Rework</TableHead>
                <TableHead className="text-right">Reject</TableHead>
                <TableHead>Defect rate</TableHead>
                <TableHead>Top defect</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => {
                const rate = Number(r.defect_rate_pct);
                return (
                  <TableRow key={r.id} tabIndex={0} className="cursor-pointer" onClick={() => onPick(r.id)} onKeyDown={(e) => e.key === "Enter" && onPick(r.id)}>
                    <TableCell>
                      <span className="num block font-semibold">{r.code}</span>
                      <span className="block max-w-48 truncate text-[0.8rem] text-muted-foreground">{r.name}</span>
                    </TableCell>
                    <TableCell className="num text-right">{r.checked}</TableCell>
                    <TableCell className="num text-right">{r.rework}</TableCell>
                    <TableCell className="num text-right">{r.rejected}</TableCell>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <span className="h-2 w-20 border border-border">
                          <span className={cn("block h-full", rate >= 10 ? "bg-danger" : rate >= 5 ? "bg-warning" : "bg-foreground")} style={{ width: `${Math.min(rate, 100)}%` }} />
                        </span>
                        <span className={cn("num text-[0.85rem]", rate >= 10 && "font-semibold text-danger")}>{rate.toFixed(1)}%</span>
                      </span>
                    </TableCell>
                    <TableCell>{r.top_defect ? defectLabel(r.top_defect) : "—"}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
      )}
    </section>
  );
}

function Analysis({ s, onLoom, onOrder }: { s: Summary; onLoom: (id: number) => void; onOrder: (id: number) => void }) {
  const top = Math.max(1, ...s.by_defect.map((d) => d.count));
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <section className="border border-border bg-card xl:col-span-2">
        <h2 className="border-b border-border px-4 py-3 text-base">Defects by type</h2>
        {s.by_defect.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">No defects marked in this period.</p>
        ) : (
          <ul className="grid gap-x-8 px-4 py-3 md:grid-cols-2">
            {s.by_defect.map((d) => (
              <li key={d.type} className="grid grid-cols-[9rem_1fr_auto] items-center gap-3 border-b border-border py-2 last:border-0">
                <span className="truncate font-medium">{defectLabel(d.type)}</span>
                <span className="h-2.5 border border-border">
                  <span className="block h-full bg-[radial-gradient(var(--foreground)_0.8px,transparent_1px)] bg-[size:3px_3px]" style={{ width: `${(d.count / top) * 100}%` }} />
                </span>
                <span className="num text-[0.85rem] text-muted-foreground">
                  {d.count} on {d.rolls} {d.rolls === 1 ? "roll" : "rolls"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <RateTable title="By loom" codeLabel="Loom" rows={s.by_loom} onPick={onLoom} />
      <RateTable title="By order" codeLabel="Order" rows={s.by_order} onPick={onOrder} />
    </div>
  );
}

// R12, R13: the QC table's day: what waits, what was decided, and where defects come from
export function QcHome() {
  useSSE(["quality"]);
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>("waiting");
  const [days, setDays] = useState(7);
  const [filters, setFilters] = useState<CheckFilters>({});
  const summary = useQcSummary(days);
  const done = params.get("done");

  const drill = (f: CheckFilters) => {
    setFilters(f);
    setTab("checked");
  };

  return (
    <>
      <PageHeader
        title="Quality check"
        description="Every roll is inspected before it reaches the finished shelf. Oldest roll first."
        actions={
          <div className="flex border border-foreground" role="radiogroup" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.days} type="button" role="radio" aria-checked={days === p.days} onClick={() => setDays(p.days)} className={cn("pressable h-10 px-4 text-[0.88rem] font-medium", days === p.days ? "bg-primary text-primary-foreground" : "hover:bg-accent")}>
                {p.label}
              </button>
            ))}
          </div>
        }
      />
      {done && (
        <p role="status" className="mb-5 border border-success/40 bg-success-soft px-4 py-3 text-[0.94rem] font-medium text-success">
          {done}. The queue is empty, nothing else to check.
        </p>
      )}
      <div className="mb-6 border border-border bg-card p-4">
        <RollFinder />
      </div>
      {summary.data ? <Strip s={summary.data} /> : <Skeleton className="mb-8 h-24 w-full" />}
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
      {tab === "waiting" && <Waiting />}
        {tab === "checked" && <Checked filters={filters} onFilters={setFilters} />}
        {tab === "analysis" &&
          (summary.data ? <Analysis s={summary.data} onLoom={(id) => drill({ machine_id: id })} onOrder={(id) => drill({ order_id: id })} /> : <Skeleton className="h-72 w-full" />)}
    </>
  );
}
