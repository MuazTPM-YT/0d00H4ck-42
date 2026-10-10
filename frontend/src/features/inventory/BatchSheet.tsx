"use client";

import { Select } from "@/components/ui/select";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { type FormEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { dateTime, humanize, inr, kg } from "@/lib/format";

import { type BatchDetail, itemLabel, qrSrc } from "./types";
import { ErrorText, selectClass, useMaster, type YarnItemOption } from "./ui";

type Action = "quarantine" | "reject" | "release";

// one batch: where its kilos are, every ledger move, reservations, activity, and the next step
export function BatchSheet({ batchId, onClose }: { batchId: number | null; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["stock", "batch", batchId],
    queryFn: () => api<BatchDetail>(`/inventory/batches/${batchId}`),
    enabled: batchId !== null,
  });
  const b = detail.data?.batch;

  return (
    <Sheet open={batchId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="flex flex-wrap items-center gap-2">
            {b?.code ?? "Batch"} {b && <StatusBadge status={b.status} />}
          </SheetTitle>
          <SheetDescription>{b ? `${itemLabel(b.yarn_item)} · lot ${b.supplier_lot ?? "—"} · ${b.supplier?.name}` : "Loading…"}</SheetDescription>
        </SheetHeader>
        <div className="grid gap-6 px-4 pb-6">
          {detail.isError && <ErrorText error={detail.error} />}
          {detail.isPending && <Skeleton className="h-48 w-full" />}
          {detail.data && <Body data={detail.data} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Body({ data }: { data: BatchDetail }) {
  const { batch: b } = data;
  return (
    <>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <Info label="Received" value={kg(b.received_kg)} />
        <Info label="Cost" value={`${inr(b.unit_cost_paise_per_kg)}/kg`} />
        <Info label="Receipt" value={`${b.receipt?.code} (${b.receipt?.status})`} />
        {/* virtual places (supplier, consumed) run negative in the ledger; show only kilos that sit somewhere */}
        <Info label="Where now" value={Object.entries(data.where).filter(([, v]) => Number(v) > 0).map(([k, v]) => `${humanize(k)} ${kg(v)}`).join(", ") || "Not moved yet"} />
      </dl>
      {b.mismatch_notes && <p className="rounded-md bg-warning-soft p-3 text-sm text-warning">{b.mismatch_notes}</p>}

      <Actions data={data} />
      <BatchLabel code={b.code} title={`${itemLabel(b.yarn_item)} · ${kg(b.received_kg)}`} />

      <section>
        <h3 className="mb-2 text-sm font-semibold">Ledger moves</h3>
        {data.moves.length === 0 ? (
          <p className="text-sm text-muted-foreground">No moves yet. Stock moves when the receipt is confirmed.</p>
        ) : (
          <ol className="grid gap-2 text-sm">
            {data.moves.map((m) => (
              <li key={m.id} className="flex flex-wrap items-baseline justify-between gap-2 rounded-md border p-2">
                <span>
                  <span className="font-medium">{humanize(m.reason)}</span> {m.from_location} → {m.to_location}
                  {m.work_order_code && <span className="text-muted-foreground"> · {m.work_order_code}</span>}
                </span>
                <span className="tabular">{kg(m.qty)}</span>
                <span className="w-full text-xs text-muted-foreground">{dateTime(m.at)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {data.reservations.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold">Reservations</h3>
          <ul className="grid gap-1 text-sm">
            {data.reservations.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-2">
                <span>{r.order_code}</span>
                <span className="tabular">{kg(r.kg)}</span>
                <StatusBadge status={r.status} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold">Activity</h3>
        <ul className="grid gap-1 text-sm">
          {data.activity.map((a, i) => (
            <li key={i} className="text-muted-foreground">
              {dateTime(a.at)} · <span className="text-foreground">{humanize(a.action)}</span>
              {a.reason && ` · “${a.reason}”`}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

// the next allowed steps for this batch and role; the server checks again
function Actions({ data }: { data: BatchDetail }) {
  const b = data.batch;
  const role = useMe().data?.role;
  const qc = useQueryClient();
  const [action, setAction] = useState<Action | null>(null);
  const done = () => {
    qc.invalidateQueries({ queryKey: ["stock"] });
    qc.invalidateQueries({ queryKey: ["orders"] });
    setAction(null);
  };
  const approve = useMutation({ mutationFn: () => api(`/inventory/batches/${b.id}/approve`, { method: "POST" }), onSuccess: done });
  const received = Object.keys(data.where).length > 0;
  const canStore = role === "store" || role === "owner";

  if (b.status === "pending_identification") return canStore ? <Identify batchId={b.id} onDone={done} /> : null;
  if (b.status === "rejected") return null;

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap gap-2">
        {b.status === "inspection" && canStore && (
          <Button size="lg" disabled={!received || approve.isPending} onClick={() => approve.mutate()}>
            Approve into store
          </Button>
        )}
        {b.status === "quarantined" && role === "owner" && (
          <Button size="lg" onClick={() => setAction("release")}>
            Release (owner)
          </Button>
        )}
        {(b.status === "inspection" || b.status === "approved") && canStore && (
          <Button size="lg" variant="outline" onClick={() => setAction("quarantine")}>
            Quarantine
          </Button>
        )}
        {(b.status === "inspection" || b.status === "quarantined") && canStore && (
          <Button size="lg" variant="outline" onClick={() => setAction("reject")}>
            Reject
          </Button>
        )}
      </div>
      {!received && b.status === "inspection" && <p className="text-sm text-muted-foreground">Confirm the receipt first, then approve.</p>}
      {b.status === "quarantined" && role !== "owner" && <p className="text-sm text-muted-foreground">Only the owner can release quarantined yarn, with a reason.</p>}
      <ErrorText error={approve.error} />
      {action && <ReasonForm batchId={b.id} action={action} onDone={done} onCancel={() => setAction(null)} />}
    </section>
  );
}

const ACTION_TEXT: Record<Action, string> = {
  quarantine: "Why is this yarn held?",
  reject: "Why is this yarn rejected?",
  release: "Why is it safe to use now?",
};

function ReasonForm({ batchId, action, onDone, onCancel }: { batchId: number; action: Action; onDone: () => void; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();
  const save = useMutation({
    mutationFn: () => api(`/inventory/batches/${batchId}/${action}`, { method: "POST", json: { reason: reason.trim() } }),
    onSuccess: onDone,
    onError: (e) => setError(e.message),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!reason.trim()) return setError("A reason is required");
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded-lg border p-3">
      <FormField name="reason" label={ACTION_TEXT[action]} error={error} required>
        <Input id="reason" name="reason" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "reason-error" : undefined} autoFocus />
      </FormField>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{humanize(action)}</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

// label was missing: pick the yarn it really is
function Identify({ batchId, onDone }: { batchId: number; onDone: () => void }) {
  const items = useMaster<YarnItemOption>("yarn-items");
  const [itemId, setItemId] = useState("");
  const [lot, setLot] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => api(`/inventory/batches/${batchId}/identify`, { method: "POST", json: { yarn_item_id: Number(itemId), supplier_lot: lot.trim() || null } }),
    onSuccess: onDone,
    onError: (e) => setErrors({ [e instanceof ApiError && e.field ? e.field : "form"]: e.message }),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!itemId) return setErrors({ yarn_item_id: "Pick the yarn" });
    save.mutate();
  }
  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded-lg border p-3">
      <p className="text-sm">Label missing. Check the cones and say what this yarn is.</p>
      <FormField name="yarn_item_id" label="Yarn" error={errors.yarn_item_id} required>
        <Select id="yarn_item_id" value={itemId} onChange={(e) => setItemId(e.target.value)} className={selectClass} aria-invalid={!!errors.yarn_item_id}>
          <option value="">Choose…</option>
          {items.data?.items.map((i) => (
            <option key={i.id} value={i.id}>{`${i.fibre} ${i.count} ${i.colour}`}</option>
          ))}
        </Select>
      </FormField>
      <FormField name="supplier_lot" label="Supplier lot (if known)" error={errors.supplier_lot}>
        <Input id="supplier_lot" value={lot} maxLength={60} onChange={(e) => setLot(e.target.value)} />
      </FormField>
      <ErrorText error={errors.form ? new Error(errors.form) : null} />
      <Button type="submit" size="lg" disabled={save.isPending}>Identify</Button>
    </form>
  );
}

// printable internal label: the batch code as QR, scanned again at issue time
export function BatchLabel({ code, title }: { code: string; title: string }) {
  return (
    <section className="flex flex-wrap items-center gap-4 rounded-lg border p-3">
      <img src={qrSrc(code)} alt={`QR code for ${code}`} className="size-24 rounded bg-white p-1" />
      <div className="min-w-24 flex-1">
        <div className="text-lg font-semibold tabular">{code}</div>
        <div className="text-sm text-muted-foreground">{title}</div>
      </div>
      <Button variant="outline" size="sm" onClick={() => printLabel(code, title)}>
        <Printer /> Print
      </Button>
    </section>
  );
}

// small window with only the label in it, so the printer gets the label and nothing else
function printLabel(code: string, title: string) {
  const w = window.open("", "_blank", "width=420,height=520");
  if (!w) return;
  const doc = w.document;
  doc.title = code;
  const box = doc.createElement("div");
  box.style.cssText = "font-family:system-ui,sans-serif;text-align:center;padding:16px";
  const img = doc.createElement("img");
  img.src = qrSrc(code);
  img.alt = code;
  img.style.width = "220px";
  img.onload = () => w.print();
  const big = doc.createElement("div");
  big.textContent = code;
  big.style.cssText = "font-size:28px;font-weight:700;margin-top:8px";
  const small = doc.createElement("div");
  small.textContent = title;
  box.append(img, big, small);
  doc.body.append(box);
}
