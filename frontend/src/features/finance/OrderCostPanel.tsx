"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { inr, metres } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { CostLine, OrderCost } from "./types";

// true cost of one order and its margin, with the allocation rule spelled out (R21)
export function OrderCostPanel({ orderId }: { orderId: string }) {
  const cost = useQuery({ queryKey: ["orders", "cost", orderId], queryFn: () => api<OrderCost>(`/finance/orders/${orderId}/cost`) });
  if (cost.isPending) return <Skeleton className="h-40 w-full" />;
  if (cost.isError) return <p className="rounded-lg border bg-card p-4 text-sm text-danger">Cost not available: {cost.error.message}</p>;
  const c = cost.data;
  return (
    <section className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-medium">Cost and margin</h2>
        <span className="text-sm text-muted-foreground">
          {metres(c.produced_m)} woven · {metres(c.passed_m)} passed · {metres(c.rejected_m)} rejected
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Fig label={c.cost_to_date ? "Cost to date" : "Total cost"} value={inr(c.total_paise)} />
        <Fig label={c.cost_provisional ? "Per metre passed (provisional)" : "Per metre passed"} value={c.cost_per_m_paise === null ? "—" : inr(c.cost_per_m_paise)} />
        <Fig label="Per roll passed" value={c.cost_per_roll_paise === null ? "—" : inr(c.cost_per_roll_paise)} />
        <Fig
          label={c.margin_paise === null ? "Margin on invoiced" : `Margin on ${metres(c.invoiced_m)} invoiced`}
          value={c.margin_paise === null ? "Not invoiced yet" : inr(c.margin_paise)}
          tone={c.margin_paise === null ? undefined : c.margin_paise >= 0 ? "text-success" : "text-danger"}
        />
      </dl>
      <div className="mt-4 grid gap-2">
        <Bucket title="Yarn" total={c.yarn_paise} lines={c.yarn} />
        <Bucket title="Machine" total={c.machine_paise} lines={c.machine} />
        <Bucket title="Labour" total={c.labour_paise} lines={c.labour} />
      </div>
      {c.reject_share_paise > 0 && (
        <p className="mt-3 text-sm text-warning">Rejected fabric carried {inr(c.reject_share_paise)} of this cost.</p>
      )}
      <details className="mt-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer">How this is worked out</summary>
        <ul className="mt-2 list-disc pl-5">{c.rules.map((r) => <li key={r}>{r}</li>)}</ul>
      </details>
    </section>
  );
}

function Fig({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md bg-muted px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("font-semibold tabular", tone)}>{value}</dd>
    </div>
  );
}

function Bucket({ title, total, lines }: { title: string; total: number; lines: CostLine[] }) {
  return (
    <details className="group rounded-md border">
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm">
        <ChevronDown className="size-4 transition group-open:rotate-180" aria-hidden />
        <span className="flex-1">{title}</span>
        <span className="tabular">{inr(total)}</span>
      </summary>
      {lines.length === 0 ? (
        <p className="px-3 pb-2 text-xs text-muted-foreground">Nothing recorded yet.</p>
      ) : (
        <ul className="divide-y border-t text-xs">
          {lines.map((l) => (
            <li key={l.label} className="flex flex-wrap gap-2 px-3 py-1.5">
              <span className="font-medium">{l.label}</span>
              <span className="text-muted-foreground">{l.detail}</span>
              <span className="ml-auto tabular">{inr(l.amount_paise)}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
