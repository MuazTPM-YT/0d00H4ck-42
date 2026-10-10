"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Truck } from "lucide-react";
import { useRouter } from "next/navigation";
import { type SubmitEvent, useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, ApiError, type Paged, qs } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { dateTime, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import type { DispatchRow, ShelfGroup } from "./types";

const LIMIT = 20;
export const VEHICLE_RE = "[A-Za-z0-9][A-Za-z0-9 \\-]{3,18}[A-Za-z0-9]";
const SELECT = "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm";

const columns: Column<DispatchRow>[] = [
  { key: "code", header: "Dispatch", cell: (d) => <span className="font-medium">{d.code}</span> },
  { key: "when", header: "Date", cell: (d) => dateTime(d.confirmed_at ?? d.created_at) },
  { key: "buyer", header: "Buyer", cell: (d) => d.buyer_name },
  { key: "order", header: "Order", cell: (d) => d.order_code },
  { key: "vehicle", header: "Vehicle", cell: (d) => d.vehicle_no ?? "—" },
  { key: "rolls", header: "Rolls", cell: (d) => d.roll_count, className: "text-right tabular" },
  { key: "metres", header: "Metres", cell: (d) => metres(d.metres), className: "text-right tabular" },
  { key: "invoice", header: "Invoice", cell: (d) => d.invoice_code ?? "—" },
  { key: "status", header: "Status", cell: (d) => <StatusBadge status={d.status} /> },
];

// gone-out register: every dispatch by date, buyer and vehicle (R16-R17)
export function DispatchList() {
  useSSE(["dispatch"]);
  const router = useRouter();
  const role = useMe().data?.role;
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState({ status: "", vehicle: "", date_from: "", date_to: "" });
  const [creating, setCreating] = useState(false);

  const query = useQuery({
    queryKey: ["dispatch", "list", filters, offset],
    queryFn: () => api<Paged<DispatchRow>>(`/dispatch/dispatches${qs({ ...filters, limit: LIMIT, offset })}`),
    placeholderData: keepPreviousData,
  });
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => {
    setFilters((f) => ({ ...f, [k]: e.target.value }));
    setOffset(0);
  };
  const canLoad = role === "dispatch" || role === "owner";

  return (
    <>
      <PageHeader
        title="Dispatches"
        description="Every truck that left the mill, and the ones being loaded now."
        actions={canLoad && <Button size="lg" onClick={() => setCreating(true)}><Plus /> New dispatch</Button>}
      />
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <select aria-label="Status" className={SELECT} value={filters.status} onChange={set("status")}>
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="loading">Loading</option>
          <option value="confirmed">Confirmed</option>
        </select>
        <Input aria-label="Vehicle" placeholder="Vehicle no." maxLength={20} value={filters.vehicle} onChange={set("vehicle")} />
        <Input aria-label="From date" type="date" value={filters.date_from} onChange={set("date_from")} />
        <Input aria-label="To date" type="date" value={filters.date_to} min={filters.date_from || undefined} onChange={set("date_to")} />
      </div>
      <DataTable
        columns={columns}
        query={query}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={(d) => router.push(`/dispatch/${d.id}`)}
        empty={<EmptyState icon={Truck} title="No dispatches match">Start one from an order that has passed rolls on the shelf.</EmptyState>}
      />
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>New dispatch</DialogTitle>
            <DialogDescription>Pick the order. Vehicle can be added before the truck leaves.</DialogDescription>
          </DialogHeader>
          {creating && <CreateDispatchForm onDone={(id) => router.push(`/dispatch/${id}`)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

// only open orders with passed rolls on the shelf are offered
export function CreateDispatchForm({ onDone, orderId }: { onDone: (id: number) => void; orderId?: number }) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const shelf = useQuery({ queryKey: ["dispatch", "shelf"], queryFn: () => api<ShelfGroup[]>("/dispatch/finished-stock") });
  const ready = (shelf.data ?? []).filter((g) => g.order_open);
  const create = useMutation({
    mutationFn: (body: { order_id: number; vehicle_no: string | null; driver: string | null }) =>
      api<{ id: number }>("/dispatch/dispatches", { method: "POST", json: body }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["dispatch"] });
      onDone(d.id);
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrors({});
    const form = e.currentTarget;
    if (!form.checkValidity()) return;
    const f = new FormData(form);
    const text = (k: string) => String(f.get(k) ?? "").trim() || null;
    create.mutate({ order_id: Number(f.get("order_id")), vehicle_no: text("vehicle_no"), driver: text("driver") });
  }

  return (
    <form noValidate onSubmit={submit} onInvalidCapture={(e) => {
      const el = e.target as HTMLInputElement;
      setErrors((p) => ({ ...p, [el.name]: el.validity.patternMismatch ? el.title : el.validationMessage }));
    }} className="grid gap-4">
      <FormField name="order_id" label="Order" required error={errors.order_id}>
        <select id="order_id" name="order_id" required defaultValue={orderId ?? ""} className={`${SELECT} h-12 text-base`} aria-invalid={!!errors.order_id}>
          <option value="" disabled>{shelf.isPending ? "Loading orders…" : ready.length ? "Choose an order" : "No order has rolls ready"}</option>
          {ready.map((g) => (
            <option key={g.order_id} value={g.order_id}>
              {g.order_code} · {g.buyer_name} · {metres(g.on_shelf_m)} on shelf
            </option>
          ))}
        </select>
      </FormField>
      <FormField name="vehicle_no" label="Vehicle no." error={errors.vehicle_no} hint="e.g. KA-01-AB-1234">
        <Input id="vehicle_no" name="vehicle_no" className="h-12 text-base uppercase" maxLength={20} pattern={VEHICLE_RE} title="Letters, digits, spaces or dashes, 5 to 20 long" aria-invalid={!!errors.vehicle_no} />
      </FormField>
      <FormField name="driver" label="Driver" error={errors.driver}>
        <Input id="driver" name="driver" className="h-12 text-base" maxLength={120} aria-invalid={!!errors.driver} />
      </FormField>
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <Button type="submit" size="lg" className="h-12" disabled={create.isPending}>
        {create.isPending ? "Creating…" : "Create and start loading"}
      </Button>
    </form>
  );
}
