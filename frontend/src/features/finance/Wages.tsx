"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, Wallet } from "lucide-react";
import { type SubmitEvent, useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type Paged, qs } from "@/lib/api";
import { date, humanize, inr, metres } from "@/lib/format";

import { useOpenParam } from "./Invoices";
import type { WageRun, WageRunDetail } from "./types";

const LIMIT = 20;
const istToday = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
// a wage run ends yesterday at the latest: today's attendance and logs can still change
const istYesterday = () => new Date(Date.now() - 86_400_000).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

const columns: Column<WageRun>[] = [
  { key: "period", header: "Period", cell: (r) => `${date(r.period_start)} – ${date(r.period_end)}` },
  { key: "workers", header: "Workers", cell: (r) => r.workers, className: "text-right tabular" },
  { key: "total", header: "Total", cell: (r) => inr(r.total_paise), className: "text-right tabular" },
  { key: "status", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
];

// wages computed from attendance and woven metres; nobody types an amount (R20)
export function Wages() {
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const { open, setOpen } = useOpenParam();
  const query = useQuery({
    queryKey: ["finance", "wage-runs", offset],
    queryFn: () => api<Paged<WageRun>>(`/finance/wage-runs${qs({ limit: LIMIT, offset })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Wages"
        description="Daily-rated: days present × day rate (half day = ½). Piece-rated weavers: metres woven × rate per metre."
        actions={<Button onClick={() => setCreating(true)}><Plus /> New wage run</Button>}
      />
      <DataTable
        columns={columns}
        query={query}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={(r) => setOpen(r.id)}
        empty={<EmptyState icon={Wallet} title="No wage runs yet" action={<Button onClick={() => setCreating(true)}><Plus /> New wage run</Button>} />}
      />
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New wage run</DialogTitle>
            <DialogDescription>Lines are worked out from attendance and loom logs for these dates.</DialogDescription>
          </DialogHeader>
          {creating && <NewRunForm onDone={(id) => { setCreating(false); setOpen(id); }} />}
        </DialogContent>
      </Dialog>
      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Wage run</DialogTitle>
            <DialogDescription>Draft can be recomputed after attendance fixes. Final locks it; paid records the payout.</DialogDescription>
          </DialogHeader>
          {open !== null && <RunDetail id={open} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function NewRunForm({ onDone }: { onDone: (id: number) => void }) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: (body: object) => api<WageRunDetail>("/finance/wage-runs", { method: "POST", json: body }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["finance"] });
      onDone(run.id);
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });
  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrors({});
    const form = e.currentTarget;
    if (!form.checkValidity()) return;
    const f = new FormData(form);
    const start = String(f.get("period_start"));
    const end = String(f.get("period_end"));
    if (end < start) return setErrors({ period_end: "End date must be on or after start date" });
    if (end >= istToday()) return setErrors({ period_end: "A wage run must end yesterday or earlier" });
    create.mutate({ period_start: start, period_end: end });
  }
  return (
    <form noValidate onSubmit={submit} onInvalidCapture={(e) => {
      const el = e.target as HTMLInputElement;
      setErrors((p) => ({ ...p, [el.name]: el.validationMessage }));
    }} className="grid gap-3">
      <FormField name="period_start" label="From" required error={errors.period_start}>
        <Input id="period_start" name="period_start" type="date" required max={istYesterday()} aria-invalid={!!errors.period_start} />
      </FormField>
      <FormField name="period_end" label="To" required error={errors.period_end}>
        <Input id="period_end" name="period_end" type="date" required max={istYesterday()} aria-invalid={!!errors.period_end} />
      </FormField>
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <Button type="submit" disabled={create.isPending}>{create.isPending ? "Working out…" : "Create draft"}</Button>
    </form>
  );
}

function RunDetail({ id }: { id: number }) {
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["finance", "wage-run", id], queryFn: () => api<WageRunDetail>(`/finance/wage-runs/${id}`) });
  const act = useMutation({
    mutationFn: (action: "recompute" | "finalize" | "pay") => api(`/finance/wage-runs/${id}/${action}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["finance"] }),
  });
  const { setOpen } = useOpenParam();
  const remove = useMutation({
    mutationFn: () => api(`/finance/wage-runs/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["finance"] });
      setOpen(null);
    },
  });
  if (run.isPending) return <Skeleton className="h-64 w-full" />;
  if (run.isError) return <EmptyState icon={AlertTriangle} title="Could not load wage run">{run.error.message}</EmptyState>;
  const r = run.data;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{date(r.period_start)} – {date(r.period_end)}</span>
        <StatusBadge status={r.status} />
        <span className="ml-auto font-semibold tabular">{inr(r.total_paise)}</span>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr><th className="px-3 py-2 font-normal">Worker</th><th className="font-normal">Type</th><th className="text-right font-normal">Days</th><th className="text-right font-normal">Metres</th><th className="text-right font-normal">Rate</th><th className="px-3 text-right font-normal">Amount</th></tr>
          </thead>
          <tbody>
            {r.lines.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">No attendance or loom output in this period.</td></tr>
            ) : r.lines.map((l) => (
              <tr key={l.worker_id} className="border-t">
                <td className="px-3 py-2">{l.worker_code} {l.worker_name}</td>
                <td>{humanize(l.wage_type)}</td>
                <td className="text-right tabular">{Number(l.days)}</td>
                <td className="text-right tabular">{l.wage_type === "piece" ? metres(l.metres) : "—"}</td>
                <td className="text-right tabular">{inr(l.rate_paise)}{l.wage_type === "piece" ? "/m" : "/day"}</td>
                <td className="px-3 text-right tabular">{inr(l.amount_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {act.isError && <p role="alert" className="text-sm text-danger">{act.error.message}</p>}
      {remove.isError && <p role="alert" className="text-sm text-danger">{remove.error.message}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {r.status === "draft" && <Button variant="outline" className="mr-auto text-danger" disabled={remove.isPending} onClick={() => window.confirm("Delete this draft wage run?") && remove.mutate()}>Delete draft</Button>}
        {r.status === "draft" && <Button variant="outline" disabled={act.isPending} onClick={() => act.mutate("recompute")}>Recompute</Button>}
        {r.status === "draft" && <Button disabled={act.isPending} onClick={() => window.confirm("Lock this wage run?") && act.mutate("finalize")}>Finalise</Button>}
        {r.status === "final" && <Button disabled={act.isPending} onClick={() => window.confirm("Mark wages as paid out?") && act.mutate("pay")}>Mark paid</Button>}
      </div>
    </div>
  );
}
