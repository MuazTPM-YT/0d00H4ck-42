"use client";

import { useQueries } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/layout/PageHeader";
import { StatStrip } from "@/components/layout/StatStrip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, apiAll, type Paged } from "@/lib/api";
import { kg } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { IssuePanel } from "./IssuePanel";
import { useStock } from "./StockScreen";
import type { Batch, Delivery } from "./types";
import { ErrorText, LevelBadge } from "./ui";

const QUEUES = [
  { status: "inspection", title: "Waiting for approval" },
  { status: "pending_identification", title: "Label missing" },
  { status: "quarantined", title: "In quarantine" },
] as const;

// store home: what needs doing now, low-stock warnings (live), and issue to production
export function StoreHome() {
  useSSE(["stock", "orders", "machines"]);
  const stock = useStock();
  const [deliveries, ...queues] = useQueries({
    queries: [
      { queryKey: ["stock", "deliveries", "open"], queryFn: () => apiAll<Delivery>("/inventory/expected-deliveries?open_only=true") },
      ...QUEUES.map((q) => ({ queryKey: ["stock", "batches", { status: q.status, count: true }], queryFn: () => api<Paged<Batch>>(`/inventory/batches?status=${q.status}&limit=1`) })),
    ],
  });
  const warnings = stock.data?.items.filter((r) => r.level !== "ok") ?? [];

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
                </span>
              </li>
            ))}
          </ul>
        </section>
        <IssuePanel />
      </div>
    </>
  );
}
