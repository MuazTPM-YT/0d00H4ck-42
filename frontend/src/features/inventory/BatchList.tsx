"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type Paged, qs } from "@/lib/api";
import { date, humanize, kg } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { BatchSheet } from "./BatchSheet";
import { type Batch, type BatchStatus, itemLabel } from "./types";
import { selectClass } from "./ui";

const LIMIT = 25;
const STATUSES: BatchStatus[] = ["inspection", "pending_identification", "quarantined", "approved", "rejected"];

const columns: Column<Batch>[] = [
  { key: "code", header: "Batch", cell: (b) => <span className="font-medium tabular">{b.code}</span> },
  { key: "yarn", header: "Yarn", cell: (b) => itemLabel(b.yarn_item), className: "whitespace-nowrap" },
  {
    key: "supplier",
    header: "Supplier · lot",
    cell: (b) => (
      <>
        <span className="block">{b.supplier?.name ?? "—"}</span>
        <span className="block text-[0.82rem] text-muted-foreground">lot {b.supplier_lot ?? "—"}</span>
      </>
    ),
  },
  { key: "kg", header: "Received", cell: (b) => kg(b.received_kg), className: "text-right" },
  {
    key: "receipt",
    header: "Receipt",
    cell: (b) => (
      <>
        <span className="block">{`${b.receipt?.code ?? "—"}${b.receipt?.status === "draft" ? " (draft)" : ""}`}</span>
        <span className="block text-[0.82rem] text-muted-foreground">{date(b.receipt?.confirmed_at ?? b.created_at)}</span>
      </>
    ),
  },
  { key: "status", header: "Status", cell: (b) => <StatusBadge status={b.status} /> },
];

// every yarn batch with filters; tap one for its ledger and actions
export function BatchList() {
  useSSE(["stock"]);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ["stock", "batches", { status, q, offset }],
    queryFn: () => api<Paged<Batch>>(`/inventory/batches${qs({ status, q, limit: LIMIT, offset })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Yarn batches"
        description="One batch per supplier lot per truck. Status moves only by approve, quarantine, release or reject."
        actions={
          <Button asChild>
            <Link href="/store/receive">Receive yarn</Link>
          </Button>
        }
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative sm:max-w-xs sm:flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input aria-label="Search batch code or lot" placeholder="Batch code or lot" maxLength={60} value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} className="pl-9" />
        </div>
        <select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={`${selectClass} sm:w-56`}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{humanize(s)}</option>
          ))}
        </select>
      </div>
      <DataTable
        columns={columns}
        query={query}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={(b) => setOpen(b.id)}
        empty={<EmptyState title={q || status ? "No batches match" : "No yarn received yet"}>{q || status ? "Clear the filters to see all batches." : "Received lots show up here."}</EmptyState>}
      />
      <BatchSheet batchId={open} onClose={() => setOpen(null)} />
    </>
  );
}
