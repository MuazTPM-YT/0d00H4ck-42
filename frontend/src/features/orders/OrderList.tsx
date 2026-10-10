"use client";

import { Select } from "@/components/ui/select";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Tabs } from "@/components/layout/Tabs";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Paged, qs } from "@/lib/api";
import { date, humanize, inr, kg, metres } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSSE } from "@/lib/useSSE";

import { DeliveryForm, type DeliveryPrefill } from "@/features/inventory/DeliveryForm";
import { ErrorText, selectClass } from "@/features/inventory/ui";

import { OrderYarnPanel } from "./OrderYarnPanel";
import type { Order, ToBuyRow } from "./types";

const LIMIT = 25;
const STATUSES = ["draft", "confirmed", "cancelled", "closed"];

// buyer-facing stage, derived on the server from work orders, rolls and trucks
type StageRow = { order_id: number; stage: string; production_stage: string | null; progress_pct: number | null; passed_m: string; shipped_m: string };
const STAGE_TEXT: Record<string, string> = {
  order_received: "Not confirmed",
  waiting_for_yarn: "Waiting for yarn",
  in_production: "In production",
  being_checked: "Being checked",
  ready_to_ship: "Ready to ship",
  partly_shipped: "Partly shipped",
  shipped: "Shipped",
  cancelled: "Cancelled",
};
const STAGE_TONE: Record<string, string> = {
  ready_to_ship: "text-success",
  shipped: "text-success",
  partly_shipped: "text-info",
  being_checked: "text-info",
  waiting_for_yarn: "text-warning",
  cancelled: "text-muted-foreground",
};

function StageCell({ s }: { s?: StageRow }) {
  if (!s) return <span className="text-muted-foreground">…</span>;
  if (s.stage === "in_production") {
    const pct = s.progress_pct ?? 0;
    return (
      <span className="grid w-36 gap-1">
        <span className="text-[0.9rem]">
          {humanize(s.production_stage ?? "production")} <span className="num text-muted-foreground">{pct}%</span>
        </span>
        <span className="h-1.5 border border-border">
          <span className="block h-full bg-foreground" style={{ width: `${pct}%` }} />
        </span>
      </span>
    );
  }
  return <span className={cn("text-[0.9rem] font-medium", STAGE_TONE[s.stage])}>{STAGE_TEXT[s.stage] ?? humanize(s.stage)}</span>;
}

const columns: Column<Order>[] = [
  { key: "code", header: "Order", cell: (o) => <span className="font-medium tabular">{o.code}</span> },
  { key: "buyer", header: "Buyer", cell: (o) => o.buyer?.name ?? "—", className: "whitespace-nowrap" },
  {
    key: "fabric",
    header: "Fabric",
    cell: (o) => (
      <>
        <span className="block">{o.fabric_type?.name ?? "—"}</span>
        <span className="block text-[0.82rem] text-muted-foreground">{o.colour}</span>
      </>
    ),
  },
  { key: "qty", header: "Quantity", cell: (o) => metres(o.qty_m), className: "text-right" },
  { key: "rate", header: "Rate / m", cell: (o) => inr(o.rate_paise_per_m), className: "text-right" },
  { key: "deadline", header: "Deadline", cell: (o) => date(o.deadline) },
  { key: "status", header: "Status", cell: (o) => <StatusBadge status={o.status} /> },
];
const stageColumn = (stages: Map<number, StageRow>): Column<Order> => ({ key: "stage", header: "Where it is", cell: (o) => <StageCell s={stages.get(o.id)} /> });

// sales desk: every order with filters, and the yarn to-buy list
export function OrderList() {
  useSSE(["orders", "stock"]);
  const [tab, setTab] = useState<"orders" | "to-buy">("orders");
  return (
    <>
      <PageHeader
        title="Orders"
        description="Confirming an order plans its work orders and reserves yarn. Anything short lands on the to-buy list."
        actions={<Button asChild><Link href="/orders/new"><Plus /> New order</Link></Button>}
      />
      <Tabs
        label="Orders view"
        value={tab}
        onChange={setTab}
        items={[
          { key: "orders", label: "All orders" },
          { key: "to-buy", label: "Yarn to buy" },
        ]}
      />
      {tab === "orders" ? <Orders /> : <ToBuy />}
    </>
  );
}

function Orders() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<Order | null>(null);
  const query = useQuery({
    queryKey: ["orders", "list", { q, status, offset }],
    queryFn: () => api<Paged<Order>>(`/orders${qs({ q, status, limit: LIMIT, offset })}`),
    placeholderData: keepPreviousData,
  });
  // one extra call per page answers "where is my order" for every row at once
  const ids = (query.data?.items ?? []).map((o) => o.id).join(",");
  const stages = useQuery({
    queryKey: ["orders", "stages", ids],
    queryFn: () => api<StageRow[]>(`/track/stages?ids=${ids}`),
    enabled: ids.length > 0,
    placeholderData: keepPreviousData,
  });
  const cols = useMemo(() => {
    const map = new Map((stages.data ?? []).map((s) => [s.order_id, s]));
    return [...columns.slice(0, -1), stageColumn(map), columns.at(-1)!];
  }, [stages.data]);
  return (
    <>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative sm:max-w-xs sm:flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input aria-label="Search orders" placeholder="Code, buyer or colour" maxLength={60} value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} className="pl-9" />
        </div>
        <Select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={`${selectClass} sm:w-48`}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
        </Select>
      </div>
      <DataTable
        columns={cols}
        query={query}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={setOpen}
        empty={<EmptyState title={q || status ? "No orders match" : "No orders yet"} action={!q && !status && <Button asChild><Link href="/orders/new">New order</Link></Button>}>{q || status ? "Clear the filters." : "Enter the first buyer order."}</EmptyState>}
      />
      <OrderSheet order={open} onClose={() => setOpen(null)} />
    </>
  );
}

function OrderSheet({ order, onClose }: { order: Order | null; onClose: () => void }) {
  const qc = useQueryClient();
  const confirm = useMutation({
    mutationFn: (id: number) => api(`/orders/${id}/confirm`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      onClose();
    },
  });
  return (
    <Sheet open={order !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">{order?.code} {order && <StatusBadge status={order.status} />}</SheetTitle>
          <SheetDescription>
            {order && `${order.buyer?.name} · ${order.fabric_type?.name} · ${order.colour} · ${metres(order.qty_m)} · due ${date(order.deadline)}`}
          </SheetDescription>
        </SheetHeader>
        {order && (
          <div className="grid gap-4 px-4 pb-6">
            {order.status === "draft" && (
              <Button size="lg" onClick={() => confirm.mutate(order.id)} disabled={confirm.isPending}>Confirm order and reserve yarn</Button>
            )}
            <ErrorText error={confirm.error} />
            <OrderYarnPanel orderId={order.id} />
            <Button asChild variant="outline"><Link href={`/orders/${order.id}`}>Open full order page</Link></Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function ToBuy() {
  const qc = useQueryClient();
  const rows = useQuery({ queryKey: ["orders", "to-buy"], queryFn: () => api<ToBuyRow[]>("/orders/to-buy") });
  const [buying, setBuying] = useState<DeliveryPrefill | null>(null);
  const reserve = useMutation({
    mutationFn: (orderId: number) => api(`/orders/${orderId}/reserve`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["stock"] });
    },
  });

  if (rows.isError) return <ErrorText error={rows.error} />;
  if (rows.isPending) return <Skeleton className="h-40 w-full" />;
  if (rows.data.length === 0) return <EmptyState title="Nothing to buy">Every confirmed order has its yarn reserved or issued.</EmptyState>;

  return (
    <>
      <p className="mb-3 text-sm text-muted-foreground">
        Short = not reserved yet. Free stock is handed out by earliest deadline first, then yarn already on order is taken off. Buy the rest.
      </p>
      <div className="overflow-x-auto rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Order</th>
              <th className="px-3 py-2 font-medium">Deadline</th>
              <th className="px-3 py-2 font-medium">Yarn</th>
              <th className="px-3 py-2 text-right font-medium">Short</th>
              <th className="px-3 py-2 text-right font-medium">Free now</th>
              <th className="px-3 py-2 text-right font-medium">On order</th>
              <th className="px-3 py-2 text-right font-medium">To buy</th>
              <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.data.map((r) => (
              <tr key={`${r.order_id}-${r.label}`} className="border-t">
                <td className="px-3 py-2 whitespace-nowrap"><span className="font-medium">{r.order_code}</span> · {r.buyer}</td>
                <td className="px-3 py-2 whitespace-nowrap">{date(r.deadline)}</td>
                <td className="px-3 py-2 whitespace-nowrap">{r.label}</td>
                <td className="px-3 py-2 text-right">{kg(r.short_kg)}</td>
                <td className="px-3 py-2 text-right">{kg(r.free_cover_kg)}</td>
                <td className="px-3 py-2 text-right">{kg(r.on_order_kg)}</td>
                <td className="px-3 py-2 text-right font-semibold">{kg(r.to_buy_kg)}</td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-2">
                    {Number(r.free_cover_kg) > 0 && (
                      <Button size="sm" variant="outline" disabled={reserve.isPending} onClick={() => reserve.mutate(r.order_id)}>Reserve now</Button>
                    )}
                    {Number(r.to_buy_kg) > 0 && r.yarn_item_id && (
                      <Button
                        size="sm"
                        onClick={() =>
                          setBuying({
                            yarn_item_id: r.yarn_item_id,
                            supplier_id: r.suggested_supplier_id,
                            expected_kg: r.to_buy_kg,
                            rate_paise_per_kg: r.suggested_rate_paise_per_kg,
                            order_id: r.order_id,
                            order_code: r.order_code,
                          })
                        }
                      >
                        Order from supplier
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorText error={reserve.error} />
      <Dialog open={buying !== null} onOpenChange={(o) => !o && setBuying(null)}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Order yarn from supplier</DialogTitle>
            <DialogDescription>Filled from the shortfall and the last supplier of this yarn. Check and save.</DialogDescription>
          </DialogHeader>
          {buying && <DeliveryForm prefill={buying} onDone={() => setBuying(null)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
