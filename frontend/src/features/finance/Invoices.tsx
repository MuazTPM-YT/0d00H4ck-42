"use client";

import { Select } from "@/components/ui/select";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileText, Printer } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Paged, qs } from "@/lib/api";
import { date, dateTime, humanize, inr, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { PaymentForm } from "./PaymentForm";
import { PrintArea } from "./PrintArea";
import { type InvoiceDetail, type InvoiceRow, SELECT } from "./types";

const LIMIT = 20;

export const invoiceColumns: Column<InvoiceRow>[] = [
  { key: "code", header: "Invoice", cell: (i) => <span className="font-medium">{i.code}</span> },
  { key: "date", header: "Date", cell: (i) => date(i.issued_at) },
  { key: "buyer", header: "Buyer", cell: (i) => i.buyer_name },
  { key: "order", header: "Order", cell: (i) => i.order_code },
  { key: "total", header: "Total", cell: (i) => inr(i.total_paise), className: "text-right tabular" },
  { key: "due", header: "Outstanding", cell: (i) => inr(i.outstanding_paise), className: "text-right tabular" },
  { key: "overdue", header: "Due", cell: (i) => (i.days_overdue ? <span className="font-medium text-danger">{i.days_overdue} days late</span> : date(i.due_date)) },
  { key: "status", header: "Status", cell: (i) => <StatusBadge status={i.status} /> },
];

// invoices are made by dispatch confirm, never typed; accounts reads, prints and collects
export function Invoices() {
  useSSE(["orders", "dispatch"]);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const { open, setOpen } = useOpenParam();
  const query = useQuery({
    queryKey: ["orders", "invoices", status, offset],
    queryFn: () => api<Paged<InvoiceRow>>(`/finance/invoices${qs({ status, limit: LIMIT, offset })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader title="Invoices" description="One invoice per truck, made from exactly the rolls loaded." />
      <div className="mb-4 max-w-xs">
        <Select aria-label="Status" className={SELECT} value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">All statuses</option>
          <option value="issued">Issued</option>
          <option value="part_paid">Part paid</option>
          <option value="paid">Paid</option>
        </Select>
      </div>
      <DataTable
        columns={invoiceColumns}
        query={query}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={(i) => setOpen(i.id)}
        empty={<EmptyState icon={FileText} title="No invoices yet">They appear when a dispatch is confirmed.</EmptyState>}
      />
      <InvoiceDialog id={open} onClose={() => setOpen(null)} />
    </>
  );
}

// ?open=12 opens a record, so other pages can link straight to it
export function useOpenParam() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const open = Number(params.get("open")) || null;
  const setOpen = (id: number | null) => router.replace(id ? `${pathname}?open=${id}` : pathname, { scroll: false });
  return { open, setOpen };
}

export function InvoiceDialog({ id, onClose }: { id: number | null; onClose: () => void }) {
  return (
    <Dialog open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Invoice</DialogTitle>
          <DialogDescription>Lines are copied from the dispatched rolls and cannot be edited.</DialogDescription>
        </DialogHeader>
        {id !== null && <InvoiceBody id={id} />}
      </DialogContent>
    </Dialog>
  );
}

function InvoiceBody({ id }: { id: number }) {
  const inv = useQuery({ queryKey: ["orders", "invoice", id], queryFn: () => api<InvoiceDetail>(`/finance/invoices/${id}`) });
  if (inv.isPending) return <Skeleton className="h-72 w-full" />;
  if (inv.isError) return <EmptyState icon={AlertTriangle} title="Could not load invoice">{inv.error.message}</EmptyState>;
  const i = inv.data;
  return (
    <div className="grid gap-4">
      <div><Button variant="outline" onClick={() => window.print()}><Printer /> Print</Button></div>
      <PrintArea>
        <div className="mb-4 flex flex-wrap justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Everest Textile Mills</div>
            <div className="text-muted-foreground">Tax invoice {i.code}</div>
          </div>
          <div className="text-right">
            <div>Date: {date(i.issued_at)}</div>
            <div>Due: {date(i.due_date)}</div>
            <div>Challan {i.dispatch_code} · {i.vehicle_no}</div>
          </div>
        </div>
        <div className="mb-4">
          <div className="font-medium">{i.buyer_name}</div>
          <div className="text-muted-foreground">GSTIN {i.buyer_gstin}{i.buyer_city && ` · ${i.buyer_city}`}</div>
          <div>Order {i.order_code} · {i.fabric}, {i.colour} · HSN 5208</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr className="border-b text-left"><th className="py-1">Roll</th><th>Shade</th><th className="text-right">Metres</th><th className="text-right">Rate/m</th><th className="text-right">Amount</th></tr></thead>
            <tbody>
              {i.lines.map((l) => (
                <tr key={l.roll_code} className="border-b">
                  <td className="py-1">{l.roll_code}</td><td>{l.shade_band ?? "—"}</td>
                  <td className="text-right tabular">{metres(l.metres)}</td>
                  <td className="text-right tabular">{inr(l.rate_paise_per_m)}</td>
                  <td className="text-right tabular">{inr(l.amount_paise)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="tabular">
              <tr><td colSpan={4} className="pt-2 text-right">Taxable value</td><td className="pt-2 text-right">{inr(i.subtotal_paise)}</td></tr>
              <tr><td colSpan={4} className="text-right">GST {Number(i.gst_pct)}%</td><td className="text-right">{inr(i.tax_paise)}</td></tr>
              <tr className="font-semibold"><td colSpan={4} className="text-right">Total</td><td className="text-right">{inr(i.total_paise)}</td></tr>
            </tfoot>
          </table>
        </div>
      </PrintArea>
      <section className="grid gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="font-medium">Payments</h3>
          <StatusBadge status={i.status} />
          <span className="text-sm text-muted-foreground">{inr(i.paid_paise)} received · {inr(i.outstanding_paise)} outstanding</span>
        </div>
        {i.payments.length > 0 && (
          <ul className="divide-y rounded-md border text-sm">
            {i.payments.map((p) => (
              <li key={p.id} className="flex flex-wrap gap-3 px-3 py-2">
                <span>{dateTime(p.received_at)}</span><span>{humanize(p.mode)}</span>
                <span className="text-muted-foreground">{p.ref}</span>
                <span className="ml-auto tabular">{inr(p.amount_paise)}</span>
              </li>
            ))}
          </ul>
        )}
        {i.outstanding_paise > 0 && <PaymentForm key={i.paid_paise} invoiceId={i.id} outstanding={i.outstanding_paise} />}
      </section>
    </div>
  );
}
