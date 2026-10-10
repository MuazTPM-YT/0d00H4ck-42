"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { StatStrip } from "@/components/layout/StatStrip";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Paged } from "@/lib/api";
import { date, humanize, kg } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { IssuePanel } from "./IssuePanel";
import type { Batch, Delivery, NeedsYarnRow, StockRow } from "./types";
import { ErrorText, LevelBadge } from "./ui";

const QUEUES = [
  { status: "inspection", title: "Waiting for approval" },
  { status: "pending_identification", title: "Label missing" },
  { status: "quarantined", title: "In quarantine" },
] as const;

// store home: jobs waiting for yarn, what needs doing now, low-stock warnings (live), and issue
export function StoreHome() {
  useSSE(["stock", "orders", "machines"]);
  const stock = useQuery({ queryKey: ["stock", "warnings"], queryFn: () => api<StockRow[]>("/inventory/stock/warnings") });
  // the WO picked from "Needs yarn"; a new key remounts the issue panel already scanned
  const [issueWo, setIssueWo] = useState<{ code: string; n: number } | null>(null);
  const [deliveries, ...queues] = useQueries({
    queries: [
      { queryKey: ["stock", "deliveries", "open"], queryFn: () => api<Paged<Delivery>>("/inventory/expected-deliveries?open_only=true&limit=100") },
      ...QUEUES.map((q) => ({ queryKey: ["stock", "batches", { status: q.status, count: true }], queryFn: () => api<Paged<Batch>>(`/inventory/batches?status=${q.status}&limit=1`) })),
    ],
  });
  const warnings = stock.data ?? [];

  return (
    <>
      <PageHeader
        title="Store"
        description="Today's yarn work. Warnings update by themselves when stock or orders change."
        actions={<Button asChild size="lg"><Link href="/store/receive">Receive yarn</Link></Button>}
      />

      <StatStrip
        stats={[
          { key: "deliveries", label: "Deliveries expected", value: (deliveries.data as Paged<Delivery> | undefined)?.total ?? "…", sub: "open supplier orders", href: "/store/receive" },
          ...QUEUES.map((q, i) => {
            const n = (queues[i].data as Paged<Batch> | undefined)?.total;
            return { key: q.status, label: q.title, value: n ?? "…", sub: "yarn batches", tone: n ? ("warn" as const) : undefined, href: "/store/batches" };
          }),
        ]}
      />

      <NeedsYarn
        onIssue={(code) => {
          setIssueWo((p) => ({ code, n: (p?.n ?? 0) + 1 }));
          requestAnimationFrame(() => document.getElementById("issue-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }));
        }}
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="grid content-start gap-3 border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-base">Low-stock warnings</h2>
            <Link href="/store/stock" className="text-sm font-medium text-info hover:underline">All stock</Link>
          </div>
          <ErrorText error={stock.error} />
          {stock.isPending && <Skeleton className="h-32 w-full" />}
          {stock.data && warnings.length === 0 && (
            <p className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="size-4" aria-hidden /> Every yarn is above its reorder level.</p>
          )}
          <ul className="scroll-panel grid max-h-[30rem] content-start gap-2">
            {warnings.map((w) => (
              <li key={w.yarn_item_id} className="flex flex-wrap items-center gap-2 border border-border p-3">
                <AlertTriangle className={w.level === "short" ? "size-4 text-danger" : "size-4 text-warning"} aria-hidden />
                <span className="font-medium">{w.label}</span>
                <LevelBadge level={w.level} />
                <span className="w-full text-sm text-muted-foreground tabular">
                  Projected {kg(w.projected_free_kg)} vs reorder at {kg(w.reorder_level_kg)} · free {kg(w.free_kg)}, still needed by orders {kg(w.needed_by_orders_kg)}
                  {Number(w.on_order_kg) > 0 && `, on order ${kg(w.on_order_kg)}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <IssuePanel key={issueWo ? `${issueWo.code}-${issueWo.n}` : "scan"} initialWo={issueWo?.code ?? null} />
      </div>
    </>
  );
}

// first-stage jobs of confirmed orders still waiting for yarn; running machines first
function NeedsYarn({ onIssue }: { onIssue: (woCode: string) => void }) {
  // queue and start only publish "machines", so poll as well as listening to stock and orders
  const rows = useQuery({ queryKey: ["stock", "needs-yarn"], queryFn: () => api<NeedsYarnRow[]>("/inventory/needs-yarn"), refetchInterval: 30_000 });
  return (
    <section className="mb-6 grid content-start gap-3 border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base">Needs yarn</h2>
        {rows.data && <span className="text-sm text-muted-foreground num">{rows.data.length} {rows.data.length === 1 ? "job" : "jobs"}</span>}
      </div>
      <ErrorText error={rows.error} />
      {rows.isPending && <Skeleton className="h-20 w-full" />}
      {rows.data && rows.data.length === 0 && (
        <p className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="size-4" aria-hidden /> Every started order has its yarn.</p>
      )}
      {rows.data && rows.data.length > 0 && (
        <div className="scroll-panel max-h-[22rem] overflow-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 font-medium">Work order</th>
                <th className="px-2 py-1.5 font-medium">Order</th>
                <th className="px-2 py-1.5 font-medium">Machine</th>
                <th className="px-2 py-1.5 font-medium">Status</th>
                <th className="px-2 py-1.5 text-right font-medium">Needed</th>
                <th className="px-2 py-1.5 text-right font-medium">Issued</th>
                <th className="px-2 py-1.5 text-right font-medium">Reserved</th>
                <th className="px-2 py-1.5 font-medium">Deadline</th>
                <th className="px-2 py-1.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.work_order_id} className="border-t">
                  <td className="px-2 py-2 whitespace-nowrap"><span className="font-medium num">{r.wo_code}</span> · {humanize(r.stage)}</td>
                  <td className="px-2 py-2 whitespace-nowrap"><span className="num">{r.order_code}</span> · {r.buyer}</td>
                  <td className="px-2 py-2 num">{r.machine_code ?? "—"}</td>
                  <td className="px-2 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-2 py-2 text-right num">{kg(r.kg_needed)}</td>
                  <td className="px-2 py-2 text-right num">{kg(r.kg_issued)}</td>
                  <td className="px-2 py-2 text-right num">{kg(r.kg_reserved)}</td>
                  <td className="px-2 py-2 whitespace-nowrap">{date(r.deadline)}</td>
                  <td className="px-2 py-2 text-right">
                    <Button size="sm" onClick={() => onIssue(r.wo_code)}>Issue</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
