"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Lightbulb, RefreshCw, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatStrip } from "@/components/layout/StatStrip";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/lib/auth";
import { dateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSSE } from "@/lib/useSSE";

import { type Insight, type InsightFilters, KIND_LABEL, type Severity, useInsightCounts, useInsights, useRunDetectors } from "./api";
import { BriefingCard } from "./AttentionList";
import { InsightSheet } from "./InsightSheet";

const LIMIT = 20;
const STATUSES = [
  { key: "open", label: "Open" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "resolved", label: "Resolved" },
  { key: "", label: "All" },
];
const EDGE: Record<Severity, string> = { critical: "border-l-danger", warn: "border-l-warning", info: "border-l-info" };
const SEVERITY_LABEL: Record<Severity, string> = { critical: "Critical", warn: "Warning", info: "Info" };
const kindLabel = (kind: string) => KIND_LABEL[kind] ?? humanize(kind);

// one finding as a ledger card: severity edge, title, the plain-language reason, where it points
function FindingCard({ i, onOpen }: { i: Insight; onOpen: () => void }) {
  const records = i.facts.records?.length ?? 0;
  return (
    <li>
      <button type="button" onClick={onOpen} className={cn("dither-hover grid w-full gap-2 border border-l-4 border-border bg-card px-4 py-3.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ember", EDGE[i.severity])}>
        <span className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
          <span className="min-w-0 flex-1 text-[1rem] font-semibold">{i.title}</span>
          <span className="flex shrink-0 items-center gap-1.5">
            <StatusBadge status={i.severity} />
            {i.status !== "open" && <StatusBadge status={i.status} />}
          </span>
        </span>
        {i.narrative && <span className="line-clamp-2 text-[0.92rem] text-body">{i.narrative}</span>}
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.82rem] text-muted-foreground">
          <span>{kindLabel(i.kind)}</span>
          <span aria-hidden>·</span>
          <span className="num">found {dateTime(i.created_at)}</span>
          {records > 0 && (
            <>
              <span aria-hidden>·</span>
              <span>
                {records} {records === 1 ? "record" : "records"} behind it
              </span>
            </>
          )}
        </span>
      </button>
    </li>
  );
}

// findings grouped by what to look at first; the open one lives in the URL (?id=12) so a link can point at it
export function InsightsPage() {
  useSSE(["insights"]);
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const role = useMe().data?.role;
  const openId = params.get("id") ? Number(params.get("id")) : null;
  const [filters, setFilters] = useState<InsightFilters>({ status: "open", severity: "", kind: "", q: "" });
  const [offset, setOffset] = useState(0);
  const insights = useInsights(filters, offset, LIMIT);
  const counts = useInsightCounts(filters.status);
  const run = useRunDetectors();

  const set = (patch: Partial<InsightFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setOffset(0);
  };
  const open = (id: number | null) => router.replace(id ? `${pathname}?id=${id}` : pathname, { scroll: false });
  const c = counts.data;
  const total = insights.data?.total ?? 0;
  const filtered = !!(filters.severity || filters.kind || filters.q);

  return (
    <>
      <PageHeader
        title="Insights"
        description="Patterns found by statistics on the mill's own records. Every number links back to the rows it came from."
        actions={
          (role === "supervisor" || role === "owner") && (
            <Button onClick={() => run.mutate()} disabled={run.isPending}>
              <RefreshCw className={run.isPending ? "animate-spin" : undefined} /> Run detectors now
            </Button>
          )
        }
      />
      {run.isError && (
        <p role="alert" className="mb-4 border border-danger/40 bg-danger-soft px-4 py-3 text-sm font-medium text-danger">
          {run.error.message}
        </p>
      )}
      {run.isSuccess && (
        <p role="status" className="mb-4 border border-border bg-card px-4 py-3 text-sm">
          Detectors ran: {run.data.created} new, {run.data.updated} updated, {run.data.unchanged} unchanged, {run.data.resolved} closed as no longer found.
        </p>
      )}
      <BriefingCard />

      {c ? (
        <StatStrip
          stats={[
            ...(["critical", "warn", "info"] as Severity[]).map((s) => ({
              key: s,
              label: (
                <>
                  <span className={cn("dot size-2", s === "critical" ? "bg-danger" : s === "warn" ? "bg-warning" : "bg-info")} aria-hidden />
                  {SEVERITY_LABEL[s]}
                </>
              ),
              value: c.by_severity[s],
              sub: filters.status ? `${humanize(filters.status).toLowerCase()} findings` : "all findings",
              tone: s === "critical" && c.by_severity[s] ? ("bad" as const) : undefined,
              pressed: filters.severity === s,
              disabled: !c.by_severity[s] && filters.severity !== s,
              onPress: () => set({ severity: filters.severity === s ? "" : s }),
            })),
            { key: "ack", label: "Being worked on", value: c.by_status.acknowledged, sub: "acknowledged" },
            { key: "resolved", label: "Resolved", value: c.by_status.resolved, sub: "fixed and closed" },
          ]}
        />
      ) : (
        <Skeleton className="mb-8 h-24 w-full" />
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <aside className="grid gap-5 lg:sticky lg:top-6" aria-label="Filters">
          <div className="grid gap-2">
            <p className="label">Status</p>
            <div className="grid border-t border-l border-border" role="radiogroup" aria-label="Status">
              {STATUSES.map((s) => {
                const on = filters.status === s.key;
                const n = s.key ? c?.by_status[s.key as keyof typeof c.by_status] : undefined;
                return (
                  <button key={s.key || "all"} type="button" role="radio" aria-checked={on} onClick={() => set({ status: s.key, severity: "" })} className={cn("pressable flex h-10 items-center justify-between gap-1 border-r border-b border-border px-3 text-[0.86rem] font-medium", on ? "bg-primary text-primary-foreground" : "bg-card hover:bg-accent")}>
                    {s.label}
                    {n !== undefined && <span className="num text-[0.75rem] opacity-70">{n}</span>}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid gap-2">
            <p className="label">Kind of finding</p>
            <ul className="scroll-panel grid max-h-[22rem] border border-border bg-card">
              <li>
                <button type="button" aria-pressed={!filters.kind} onClick={() => set({ kind: "" })} className={cn("flex h-10 w-full items-center justify-between border-b border-border px-3 text-left text-[0.9rem]", !filters.kind ? "bg-accent font-semibold" : "hover:bg-accent")}>
                  Every kind
                  <span className="num text-[0.8rem] text-muted-foreground">{c?.by_kind.reduce((s, k) => s + k.count, 0) ?? ""}</span>
                </button>
              </li>
              {c?.by_kind.map((k) => (
                <li key={k.kind}>
                  <button type="button" aria-pressed={filters.kind === k.kind} onClick={() => set({ kind: filters.kind === k.kind ? "" : k.kind })} className={cn("flex min-h-10 w-full items-center justify-between gap-2 border-b border-border px-3 py-2 text-left text-[0.9rem] last:border-0", filters.kind === k.kind ? "bg-accent font-semibold" : "hover:bg-accent")}>
                    <span className="min-w-0">{kindLabel(k.kind)}</span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      {k.critical > 0 && (
                        <span className="num border border-danger/40 bg-danger-soft px-1 text-[0.72rem] text-danger" title={`${k.critical} critical`}>
                          {k.critical}
                        </span>
                      )}
                      <span className="num text-[0.8rem] text-muted-foreground">{k.count}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <section className="grid min-w-0 gap-3" aria-label="Findings">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-56 flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input aria-label="Search findings" placeholder="Search: LM-03, belt slip, SO-000005…" maxLength={80} value={filters.q} onChange={(e) => set({ q: e.target.value })} className="pl-9" />
            </div>
            {filtered && (
              <Button variant="ghost" onClick={() => set({ severity: "", kind: "", q: "" })}>
                <X /> Clear filters
              </Button>
            )}
          </div>

          {insights.isError ? (
            <EmptyState icon={AlertTriangle} title="Could not load findings" action={<Button variant="outline" onClick={() => insights.refetch()}>Try again</Button>}>
              {insights.error.message}
            </EmptyState>
          ) : insights.isPending ? (
            Array.from({ length: 4 }, (_, n) => <Skeleton key={n} className="h-24 w-full" />)
          ) : total === 0 ? (
            <EmptyState icon={Lightbulb} title={filtered ? "No findings match" : filters.status === "open" ? "Nothing open" : "No findings here"}>
              {filtered ? "Clear the filters to see everything." : "Detectors run every 5 minutes over the mill's records."}
            </EmptyState>
          ) : (
            <>
              <ul className={cn("grid gap-2", insights.isPlaceholderData && "opacity-60")}>
                {insights.data.items.map((i) => (
                  <FindingCard key={i.id} i={i} onOpen={() => open(i.id)} />
                ))}
              </ul>
              <div className="flex items-center justify-between gap-2 text-[0.88rem] text-muted-foreground">
                <span className="num">
                  {offset + 1}–{Math.min(offset + LIMIT, total)} of {total}, worst first
                </span>
                <div className="flex gap-2">
                  <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
                    <ChevronLeft />
                  </Button>
                  <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>
                    <ChevronRight />
                  </Button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
      <InsightSheet id={openId} onClose={() => open(null)} />
    </>
  );
}
