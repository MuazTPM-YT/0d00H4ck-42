"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { IndianRupee, Wallet } from "lucide-react";
import { useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { api, apiAll, type Paged, qs } from "@/lib/api";
import { dateTime, humanize, inr } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { InvoiceDialog, invoiceColumns, useOpenParam } from "./Invoices";
import type { InvoiceRow, PaymentRow } from "./types";

const LIMIT = 20;

const paymentColumns: Column<PaymentRow>[] = [
  { key: "at", header: "Received", cell: (p) => dateTime(p.received_at) },
  { key: "buyer", header: "Buyer", cell: (p) => p.buyer_name },
  { key: "invoice", header: "Invoice", cell: (p) => p.invoice_code },
  { key: "mode", header: "Mode", cell: (p) => humanize(p.mode) },
  { key: "ref", header: "Reference", cell: (p) => p.ref ?? "—" },
  { key: "amount", header: "Amount", cell: (p) => inr(p.amount_paise), className: "text-right tabular" },
];

// who still owes us (oldest due first), and the money that came in (R24)
export function Payments() {
  useSSE(["orders", "dispatch"]);
  const { open, setOpen } = useOpenParam();
  const [dueOffset, setDueOffset] = useState(0);
  const [payOffset, setPayOffset] = useState(0);
  const due = useQuery({
    queryKey: ["orders", "outstanding", dueOffset],
    queryFn: () => api<Paged<InvoiceRow>>(`/finance/invoices${qs({ outstanding: true, limit: LIMIT, offset: dueOffset })}`),
    placeholderData: keepPreviousData,
  });
  const paid = useQuery({
    queryKey: ["orders", "payments", payOffset],
    queryFn: () => api<Paged<PaymentRow>>(`/finance/payments${qs({ limit: LIMIT, offset: payOffset })}`),
    placeholderData: keepPreviousData,
  });
  // receivables over every outstanding invoice, not just the page on screen
  const allDue = useQuery({
    queryKey: ["orders", "outstanding", "all"],
    queryFn: () => apiAll<InvoiceRow>("/finance/invoices?outstanding=true"),
  });
  const totalDue = (allDue.data?.items ?? []).reduce((s, i) => s + i.outstanding_paise, 0);

  return (
    <>
      <PageHeader title="Payments" description="Tap an outstanding invoice to record money received against it." />
      <h2 className="mb-2 font-medium">
        Outstanding {due.data && `· ${due.data.total} invoices`}{allDue.data && ` · ${inr(totalDue)}`}
      </h2>
      <DataTable
        columns={invoiceColumns}
        query={due}
        offset={dueOffset}
        limit={LIMIT}
        onOffsetChange={setDueOffset}
        onRowClick={(i) => setOpen(i.id)}
        empty={<EmptyState icon={Wallet} title="Nothing outstanding">Every invoice is paid in full.</EmptyState>}
      />
      <h2 className="mt-8 mb-2 font-medium">Received</h2>
      <DataTable
        columns={paymentColumns}
        query={paid}
        offset={payOffset}
        limit={LIMIT}
        onOffsetChange={setPayOffset}
        onRowClick={(p) => setOpen(p.invoice_id)}
        empty={<EmptyState icon={IndianRupee} title="No payments yet" />}
      />
      <InvoiceDialog id={open} onClose={() => setOpen(null)} />
    </>
  );
}
