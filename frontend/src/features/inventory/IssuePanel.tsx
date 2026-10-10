"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { date, humanize, kg } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useOpenWorkOrders } from "@/features/production/api";

import { type IssuePlan, newIdemKey, type PlanLine } from "./types";
import { ErrorText, ScanField } from "./ui";

const KG_RE = /^\d+(\.\d{1,3})?$/;

// store floor screen: scan work order, scan batch, confirm kilos. Oldest reserved batch first (FIFO).
export function IssuePanel() {
  const qc = useQueryClient();
  const [woCode, setWoCode] = useState<string | null>(null);
  const [picked, setPicked] = useState<PlanLine | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const plan = useQuery({
    queryKey: ["stock", "issue-plan", woCode],
    queryFn: () => api<IssuePlan>(`/inventory/issue-plan?work_order=${encodeURIComponent(woCode!)}`),
    enabled: woCode !== null,
    retry: false,
  });

  const lines = [...(plan.data?.reserved ?? []), ...(plan.data?.free ?? [])];
  const fifoNext = plan.data?.reserved[0]?.yarn_batch_id;

  function scanBatch(code: string) {
    const hit = lines.find((l) => l.code.toLowerCase() === code.trim().toLowerCase());
    setScanError(hit ? null : `${code} is not approved free or reserved yarn for this order`);
    setPicked(hit ?? null);
  }

  return (
    <section className="grid content-start gap-4 rounded-lg border bg-card p-4">
      <h2 className="font-semibold">Issue yarn to production</h2>
      <ScanField
        id="wo-scan"
        label="1. Work order"
        placeholder="WO-000001"
        onScan={(v) => {
          setWoCode(v);
          setPicked(null);
          setDone(null);
          setScanError(null);
        }}
      />
      {!woCode && <YarnJobs onPick={setWoCode} />}
      <ErrorText error={plan.error} />
      {plan.data && (
        <>
          <p className="text-sm">
            <span className="font-medium">{plan.data.work_order.code}</span> · {humanize(plan.data.work_order.stage)} for {plan.data.work_order.order_code} ·{" "}
            <StatusBadge status={plan.data.work_order.status} />
          </p>
          {lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">No approved yarn for this order. Check the to-buy list.</p>
          ) : (
            <>
              <ScanField id="batch-scan" label="2. Batch (or tap one below)" placeholder="YB-000001" onScan={scanBatch} />
              {scanError && <p role="alert" className="text-sm text-danger">{scanError}</p>}
              <ul className="grid gap-2">
                {lines.map((l) => (
                  <li key={l.yarn_batch_id}>
                    <button
                      type="button"
                      onClick={() => { setPicked(l); setScanError(null); }}
                      aria-pressed={picked?.yarn_batch_id === l.yarn_batch_id}
                      className={cn(
                        "flex min-h-14 w-full flex-wrap items-center gap-2 pressable rounded-xl border p-3 text-left [@media(hover:hover)]:hover:border-input",
                        picked?.yarn_batch_id === l.yarn_batch_id && "border-primary bg-accent",
                      )}
                    >
                      <span className="font-medium tabular">{l.code}</span>
                      {l.yarn_batch_id === fifoNext && <span className="rounded-full bg-info-soft px-2 py-0.5 text-xs text-info">FIFO next</span>}
                      <span className="text-sm text-muted-foreground">{l.label} · lot {l.supplier_lot ?? "—"}</span>
                      <span className="ml-auto text-sm tabular">
                        {Number(l.reserved_for_order_kg) > 0 ? `reserved ${kg(l.reserved_for_order_kg)}` : `free ${kg(l.free_kg)}`}
                      </span>
                      <span className="w-full text-xs text-muted-foreground">received {date(l.received_at)} · {kg(l.store_kg)} in store</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {picked && (
            <IssueForm
              key={picked.yarn_batch_id}
              line={picked}
              workOrderId={plan.data.work_order.id}
              onDone={(msg) => {
                setDone(msg);
                setPicked(null);
                qc.invalidateQueries({ queryKey: ["stock"] });
                qc.invalidateQueries({ queryKey: ["orders"] });
              }}
            />
          )}
          {done && <p role="status" className="rounded-md bg-success-soft p-3 text-sm text-success">{done}</p>}
          {plan.data.on_floor.length > 0 && <ReturnList plan={plan.data} onDone={setDone} />}
        </>
      )}
    </section>
  );
}

// weaving jobs queued or running take yarn; tap one instead of scanning its code
function YarnJobs({ onPick }: { onPick: (code: string) => void }) {
  const open = useOpenWorkOrders();
  const jobs = (open.data ?? []).filter((w) => w.status !== "waiting" && w.stage === "weaving" && !w.roll_id);
  if (open.isError) return <ErrorText error={open.error} />;
  if (!open.data) return null;
  if (jobs.length === 0) return <p className="text-sm text-muted-foreground">No weaving job is queued or running.</p>;
  return (
    <div className="grid gap-2">
      <p className="text-sm font-medium">Jobs that take yarn</p>
      <ul className="scroll-panel grid max-h-60 gap-2">
        {jobs.map((w) => (
          <li key={w.id}>
            <button type="button" onClick={() => onPick(w.code)} className="pressable flex w-full flex-wrap items-center gap-2 border p-2 text-left text-sm [@media(hover:hover)]:hover:border-input">
              <span className="font-medium tabular">{w.code}</span>
              <span className="text-muted-foreground">{humanize(w.stage)} · {w.order_code}</span>
              <StatusBadge status={w.status} className="ml-auto" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function IssueForm({ line, workOrderId, onDone }: { line: PlanLine; workOrderId: number; onDone: (msg: string) => void }) {
  const reserved = Number(line.reserved_for_order_kg);
  const [amount, setAmount] = useState(reserved > 0 ? line.reserved_for_order_kg : "");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [key] = useState(newIdemKey);
  const over = KG_RE.test(amount) && Number(amount) > reserved;

  const issue = useMutation({
    mutationFn: () =>
      api("/inventory/issues", {
        method: "POST",
        json: { work_order_id: workOrderId, yarn_batch_id: line.yarn_batch_id, kg: amount, reason: over ? reason.trim() : null, source: "scanner", idempotency_key: key },
      }),
    onSuccess: () => onDone(`Issued ${kg(amount)} of ${line.code}.`),
    onError: (e) => setErrors({ form: e.message }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!KG_RE.test(amount) || Number(amount) <= 0) errs.kg = "Kilos above 0, up to 3 decimals";
    if (over && !reason.trim()) errs.reason = `More than the ${kg(line.reserved_for_order_kg)} reserved: say why`;
    setErrors(errs);
    if (!Object.keys(errs).length) issue.mutate();
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded-lg border p-3">
      <FormField name="issue_kg" label={`3. Kilos of ${line.code}`} error={errors.kg} required>
        <Input id="issue_kg" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} aria-invalid={!!errors.kg} className="h-12 text-base md:text-base" />
      </FormField>
      {over && (
        <FormField name="issue_reason" label="Reason for over-issue" error={errors.reason} required>
          <Input id="issue_reason" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} aria-invalid={!!errors.reason} className="h-12" />
        </FormField>
      )}
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <Button type="submit" size="lg" className="h-12" disabled={issue.isPending}>Issue to floor</Button>
    </form>
  );
}

function ReturnList({ plan, onDone }: { plan: IssuePlan; onDone: (msg: string) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const [amount, setAmount] = useState("");
  const [key, setKey] = useState(newIdemKey);
  const back = useMutation({
    mutationFn: (batchId: number) => api("/inventory/returns", { method: "POST", json: { work_order_id: plan.work_order.id, yarn_batch_id: batchId, kg: amount, idempotency_key: key } }),
    onSuccess: () => {
      onDone(`Returned ${kg(amount)} to store.`);
      setOpen(null);
      setKey(newIdemKey());
      qc.invalidateQueries({ queryKey: ["stock"] });
    },
  });
  return (
    <div className="grid gap-2 border-t pt-3">
      <h3 className="text-sm font-medium">On the floor for {plan.work_order.code}</h3>
      {plan.on_floor.map((f) => (
        <div key={f.yarn_batch_id} className="grid gap-2">
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="tabular">{f.code} · {kg(f.kg)}</span>
            <Button variant="outline" onClick={() => { setOpen(f.yarn_batch_id); setAmount(f.kg); }}>Return unused</Button>
          </div>
          {open === f.yarn_batch_id && (
            <form
              noValidate
              onSubmit={(e) => { e.preventDefault(); if (KG_RE.test(amount) && Number(amount) > 0) back.mutate(f.yarn_batch_id); }}
              className="flex flex-wrap items-end gap-2"
            >
              <FormField name={`ret-${f.yarn_batch_id}`} label="Kilos back to store">
                <Input id={`ret-${f.yarn_batch_id}`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-11 w-32" />
              </FormField>
              <Button type="submit" className="h-11" disabled={back.isPending}>Return</Button>
              <ErrorText error={back.error} />
            </form>
          )}
        </div>
      ))}
    </div>
  );
}
