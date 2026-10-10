"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Paged, qs } from "@/lib/api";
import { date, humanize, inr, kg, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { DeliveryForm, type DeliveryPrefill } from "@/features/inventory/DeliveryForm";
import { ErrorText, selectClass } from "@/features/inventory/ui";

import { OrderYarnPanel } from "./OrderYarnPanel";
import type { Order, ToBuyRow } from "./types";

const LIMIT = 25;
const STATUSES = ["draft", "confirmed", "cancelled", "closed"];

const columns: Column<Order>[] = [
  { key: "code", header: "Order", cell: (o) => <span className="font-medium tabular">{o.code}</span> },
  { key: "buyer", header: "Buyer", cell: (o) => o.buyer?.name ?? "—", className: "whitespace-nowrap" },
  { key: "fabric", header: "Fabric", cell: (o) => o.fabric_type?.name ?? "—", className: "whitespace-nowrap" },
  { key: "colour", header: "Colour", cell: (o) => o.colour },
  { key: "qty", header: "Quantity", cell: (o) => metres(o.qty_m), className: "text-right" },
  { key: "rate", header: "Rate / m", cell: (o) => inr(o.rate_paise_per_m), className: "text-right" },
  { key: "deadline", header: "Deadline", cell: (o) => date(o.deadline) },
  { key: "status", header: "Status", cell: (o) => <StatusBadge status={o.status} /> },
];

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
      <div className="mb-4 flex gap-2" role="tablist" aria-label="Orders view">
        <Button role="tab" aria-selected={tab === "orders"} variant={tab === "orders" ? "secondary" : "ghost"} onClick={() => setTab("orders")}>All orders</Button>
        <Button role="tab" aria-selected={tab === "to-buy"} variant={tab === "to-buy" ? "secondary" : "ghost"} onClick={() => setTab("to-buy")}>Yarn to buy</Button>
      </div>
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
  return (
    <>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative sm:max-w-xs sm:flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input aria-label="Search orders" placeholder="Code, buyer or colour" maxLength={60} value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} className="pl-9" />
        </div>
        <select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={`${selectClass} sm:w-48`}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
        </select>
      </div>
      <DataTable
        columns={columns}
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
