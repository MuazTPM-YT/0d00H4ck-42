"use client";

import { type UseQueryResult, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Printer, XCircle } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, ApiError, type Paged } from "@/lib/api";
import { date, humanize, inr, kg, paiseToRupees, rupeesToPaise } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";
import { cn } from "@/lib/utils";

import { BatchSheet } from "./BatchSheet";
import { DeliveryForm } from "./DeliveryForm";
import { type Batch, type Delivery, itemLabel, type LabelCheck, type Receipt, type SampleLabel } from "./types";
import { ErrorText, ScanField, selectClass } from "./ui";

const KG_RE = /^\d+(\.\d{1,3})?$/;
const FIELD_NAME: Record<string, string> = {
  fibre: "Fibre",
  count: "Count",
  colour: "Colour",
  delivery_kg: "Kg vs delivery left",
  weighed_kg: "Weighed vs label",
};

// R1: scan a supplier label, compare with the expected delivery, add the lot, confirm the truck
export function ReceiveScreen() {
  useSSE(["stock"]);
  const qc = useQueryClient();
  const [receiptId, setReceiptId] = useState<number | null>(null);
  const [deliveryId, setDeliveryId] = useState("");
  const [vehicle, setVehicle] = useState("");
  // rupees per kg; only asked when no yarn request prices the truck
  const [rate, setRate] = useState("");
  const [check, setCheck] = useState<{ payload: string; result: LabelCheck } | null>(null);
  const [weighed, setWeighed] = useState("");
  const [mode, setMode] = useState<"scan" | "missing" | "manual">("scan");
  const [lastLine, setLastLine] = useState<{ batch: Batch; created: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Receipt | null>(null);
  const [newDelivery, setNewDelivery] = useState(false);
  const [openBatch, setOpenBatch] = useState<number | null>(null);

  const deliveries = useQuery({
    queryKey: ["stock", "deliveries", "open"],
    queryFn: () => api<Paged<Delivery>>("/inventory/expected-deliveries?open_only=true&limit=100"),
  });
  const drafts = useQuery({
    queryKey: ["stock", "receipts", "draft"],
    queryFn: () => api<Paged<Receipt>>("/inventory/receipts?status=draft&limit=20"),
  });
  const receipt = useQuery({
    queryKey: ["stock", "receipt", receiptId],
    queryFn: () => api<Receipt>(`/inventory/receipts/${receiptId}`),
    enabled: receiptId !== null,
  });
  const demo = useQuery({ queryKey: ["stock", "sample-labels"], queryFn: () => api<SampleLabel[]>("/inventory/sample-labels") });
  const needRate = receiptId ? !receipt.data?.expected_delivery : !deliveryId;
  // after each lot the cursor goes back to the scan box, so the next scan is never lost
  const focusScan = () => requestAnimationFrame(() => document.getElementById("label-scan")?.focus());

  const fail = (e: Error) => setError(e instanceof ApiError && e.field === "vehicle_no" ? `Vehicle number: ${e.message}` : e.message);

  const scan = useMutation({
    mutationFn: (payload: string) =>
      api<LabelCheck>("/inventory/labels/check", {
        method: "POST",
        json: { payload, expected_delivery_id: receipt.data?.expected_delivery?.id ?? (deliveryId ? Number(deliveryId) : null) },
      }),
    onMutate: () => {
      setError(null);
      setLastLine(null);
    },
    onSuccess: (result, payload) => {
      setCheck({ payload, result });
      setWeighed(result.label.label_kg);
      if (result.delivery && !receiptId) setDeliveryId(String(result.delivery.id));
      if (!result.delivery && !rate && result.suggested_rate_paise_per_kg) setRate(paiseToRupees(result.suggested_rate_paise_per_kg));
      requestAnimationFrame(() => (document.getElementById("weighed") as HTMLInputElement | null)?.select());
    },
    onError: (e, payload) => {
      setError(`${e.message} Scanned: "${payload}"`);
      focusScan();
    },
  });

  // the draft receipt is made on the first lot, so the store never fills a separate form
  async function ensureReceipt(): Promise<number> {
    if (receiptId) return receiptId;
    const d = deliveryId ? Number(deliveryId) : null;
    const supplier = check?.result.supplier.id ?? null;
    const r = await api<Receipt>("/inventory/receipts", {
      method: "POST",
      json: { expected_delivery_id: d, supplier_id: d ? null : supplier, vehicle_no: vehicle.trim() || null },
    });
    setReceiptId(r.id);
    return r.id;
  }

  const addLine = useMutation({
    mutationFn: async (body: object) => {
      const paise = needRate ? rupeesToPaise(rate) : null;
      if (needRate && !paise) throw new ApiError(422, "validation_error", "No yarn request for this truck: enter the rate in ₹ per kg first", "rate");
      const id = await ensureReceipt();
      return api<{ batch: Batch; created: boolean }>(`/inventory/receipts/${id}/lines`, { method: "POST", json: { ...body, rate_paise_per_kg: paise } });
    },
    onSuccess: (line) => {
      setLastLine(line);
      setCheck(null);
      setMode("scan");
      qc.invalidateQueries({ queryKey: ["stock"] });
      focusScan();
    },
    onError: (e) => {
      fail(e);
      if (e instanceof ApiError && e.field === "rate") requestAnimationFrame(() => document.getElementById("rate")?.focus());
    },
  });

  const confirm = useMutation({
    mutationFn: () => api<Receipt>(`/inventory/receipts/${receiptId}/confirm`, { method: "POST" }),
    onSuccess: (r) => {
      setConfirmed(r);
      setReceiptId(null);
      setDeliveryId("");
      setVehicle("");
      setRate("");
      setLastLine(null);
      qc.invalidateQueries({ queryKey: ["stock"] });
    },
    onError: fail,
  });

  function addScanned(e: FormEvent) {
    e.preventDefault();
    if (!KG_RE.test(weighed) || Number(weighed) <= 0) return setError("Weighed kilos must be above 0, up to 3 decimals");
    addLine.mutate({ payload: check!.payload, received_kg: weighed });
  }

  const busy = addLine.isPending || scan.isPending;
  const r = receipt.data;

  return (
    <>
      <PageHeader
        title="Receive yarn"
        description="Scan each supplier label. Spec mismatch goes to quarantine; weight gaps over 2% are flagged, never adjusted. Stock moves only when you confirm the receipt."
        actions={
          <>
            <Button asChild variant="outline">
              <Link href="/store/receive/labels"><Printer /> Sample labels</Link>
            </Button>
            <Button onClick={() => setNewDelivery(true)}><Plus /> Expected delivery</Button>
          </>
        }
      />

      {confirmed && (
        <div role="status" className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-success bg-success-soft p-4 text-success">
          <CheckCircle2 aria-hidden />
          <span className="flex-1">
            {confirmed.code} confirmed: {confirmed.batches.length} lots, {kg(confirmed.total_kg)}, bill {inr(confirmed.bill_amount_paise)}. Approve batches after inspection.
          </span>
          <Button asChild variant="outline" size="sm"><Link href="/store/batches">Open batches</Link></Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirmed(null)}>Dismiss</Button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="grid content-start gap-4 rounded-lg border bg-card p-4">
          <h2 className="font-semibold">{r ? `Truck ${r.code} · ${r.supplier_name}` : "New truck"}</h2>
          {!r && (
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField name="delivery" label="Expected delivery" hint="Picked for you when a label matches.">
                <select id="delivery" value={deliveryId} onChange={(e) => setDeliveryId(e.target.value)} className={`${selectClass} h-11`}>
                  <option value="">Match from the label</option>
                  {deliveries.data?.items.map((d) => (
                    <option key={d.id} value={d.id}>{`${d.supplier_code} · ${d.label} · ${kg(d.expected_kg)}`}</option>
                  ))}
                </select>
              </FormField>
              <FormField name="vehicle" label="Vehicle number" hint="e.g. KA-05-MN-4521">
                <Input id="vehicle" value={vehicle} maxLength={20} onChange={(e) => setVehicle(e.target.value)} className="h-11" />
              </FormField>
            </div>
          )}
          {needRate && (
            <FormField name="rate" label="Rate (₹ per kg)" required hint="No yarn request prices this truck. A scan fills in this supplier's last rate.">
              <Input id="rate" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="e.g. 285" className="h-11 sm:max-w-[calc(50%-0.5rem)]" />
            </FormField>
          )}

          <div className="flex flex-wrap gap-2" role="tablist" aria-label="How to enter the lot">
            {(["scan", "manual", "missing"] as const).map((m) => (
              <Button key={m} role="tab" aria-selected={mode === m} variant={mode === m ? "secondary" : "ghost"} onClick={() => { setMode(m); setError(null); }}>
                {m === "scan" ? "Scan label" : m === "manual" ? "Type label" : "Label missing"}
              </Button>
            ))}
          </div>

          {mode === "scan" && (
            <>
              <ScanField id="label-scan" label="Supplier label" placeholder="SUP=…;LOT=…;FIB=…;CNT=…;COL=…;KG=…" onScan={(v) => scan.mutate(v)} disabled={busy} autoFocus camera />
              <DemoLabels labels={demo.data ?? []} disabled={busy} onPick={(payload) => scan.mutate(payload)} />
            </>
          )}
          {mode === "manual" && <ManualLine busy={busy} onAdd={(body) => addLine.mutate(body)} />}
          {mode === "missing" && <MissingLine busy={busy} onAdd={(body) => addLine.mutate(body)} />}

          {error && <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">{error}</p>}

          {check && mode === "scan" && (
            <form onSubmit={addScanned} noValidate className="grid gap-3 rounded-lg border p-3">
              <div className="text-sm">
                <span className="font-medium">{check.result.supplier.name}</span> · lot {check.result.label.supplier_lot}
                {check.result.delivery ? ` · delivery #${check.result.delivery.id}` : " · no open delivery found"}
              </div>
              <Comparison rows={check.result.comparison} />
              <FormField name="weighed" label="Weighed kilos" hint="Defaults to the label. Change it if the scale says otherwise." required>
                <Input id="weighed" inputMode="decimal" value={weighed} onChange={(e) => setWeighed(e.target.value)} className="h-12 text-base md:text-base" />
              </FormField>
              <Button type="submit" size="lg" className="h-12" disabled={busy}>
                {check.result.comparison.some((c) => c.blocks && !c.ok) ? "Add lot (goes to quarantine)" : "Add lot"}
              </Button>
            </form>
          )}

          {lastLine && (
            <p role="status" className="text-sm">
              {lastLine.created ? "Added" : "Already on this truck:"} <span className="font-medium">{lastLine.batch.code}</span> · <StatusBadge status={lastLine.batch.status} />
            </p>
          )}
        </section>

        <section className="grid content-start gap-3 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">Lots on this truck</h2>
            {r && <span className="text-sm text-muted-foreground tabular">{kg(r.total_kg)}</span>}
          </div>
          {!r || r.batches.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing yet. Scan the first label.</p>
          ) : (
            <ul className="grid gap-2">
              {r.batches.map((b) => (
                <li key={b.id}>
                  <button type="button" onClick={() => setOpenBatch(b.id)} className="flex min-h-12 w-full flex-wrap items-center gap-2 pressable rounded-xl border p-3 text-left [@media(hover:hover)]:hover:border-input">
                    <span className="font-medium tabular">{b.code}</span>
                    <span className="text-sm text-muted-foreground">{itemLabel(b.yarn_item)} · lot {b.supplier_lot ?? "—"}</span>
                    <span className="ml-auto tabular">{kg(b.received_kg)}</span>
                    <StatusBadge status={b.status} />
                    {b.mismatch_notes && <span className="w-full text-xs text-warning">{b.mismatch_notes}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {r && (
            <Button size="lg" className="h-12" disabled={r.batches.length === 0 || confirm.isPending} onClick={() => confirm.mutate()}>
              Confirm receipt ({r.batches.length} {r.batches.length === 1 ? "lot" : "lots"})
            </Button>
          )}
          <ErrorText error={receipt.error} />

          {!r && (drafts.data?.items.length ?? 0) > 0 && (
            <div className="grid gap-2 border-t pt-3">
              <h3 className="text-sm font-medium">Trucks not confirmed yet</h3>
              {drafts.data!.items.map((d) => (
                <Button key={d.id} variant="outline" className="justify-between" onClick={() => setReceiptId(d.id)}>
                  <span>{d.code} · {d.supplier_name}</span>
                  <span className="text-muted-foreground">{d.batches.length} lots</span>
                </Button>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="mt-8">
        <h2 className="mb-3 font-semibold">Expected deliveries</h2>
        <DeliveryTable query={deliveries} />
      </section>

      <Dialog open={newDelivery} onOpenChange={setNewDelivery}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>New expected delivery</DialogTitle>
            <DialogDescription>What the supplier said they are sending.</DialogDescription>
          </DialogHeader>
          {newDelivery && <DeliveryForm onDone={() => setNewDelivery(false)} />}
        </DialogContent>
      </Dialog>
      <BatchSheet batchId={openBatch} onClose={() => setOpenBatch(null)} />
    </>
  );
}

// demo: no real label in hand. One tap scans a ready-made label: a requested delivery if there is
// one, else walk-in yarn from a known supplier (the truck then needs a rate)
function DemoLabels({ labels, disabled, onPick }: { labels: SampleLabel[]; disabled: boolean; onPick: (payload: string) => void }) {
  const shown = [...labels.filter((l) => l.kind === "match"), ...labels.filter((l) => l.kind === "walk_in"), ...labels.filter((l) => l.kind === "wrong_colour")].slice(0, 6);
  if (!shown.length) return null;
  return (
    <details className="group border border-dashed border-border px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium text-muted-foreground select-none group-open:mb-2 group-open:text-foreground">No label in hand? Use a demo label</summary>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {shown.map((l) => (
          <li key={l.payload}>
            <button type="button" disabled={disabled} onClick={() => onPick(l.payload)} className={cn("pressable grid w-full gap-0.5 border border-border bg-card px-3 py-2 text-left text-sm hover:border-foreground disabled:opacity-50", l.kind === "wrong_colour" && "border-danger/50")}>
              <span className="font-medium">{l.title}</span>
              <span className="text-[0.8rem] text-muted-foreground">
                {l.supplier} · {kg(l.kg)} · {l.kind === "match" ? "matches a request" : l.kind === "walk_in" ? "no request (walk-in)" : "wrong colour test"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[0.8rem] text-muted-foreground">
        Or print them from <Link href="/store/receive/labels" className="underline underline-offset-2">Sample labels</Link> and scan for real.
      </p>
    </details>
  );
}

// expected vs actual, side by side; a failed spec row quarantines
function Comparison({ rows }: { rows: LabelCheck["comparison"] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-muted-foreground">
          <th className="py-1 font-normal">Check</th>
          <th className="py-1 font-normal">Expected</th>
          <th className="py-1 font-normal">Label / scale</th>
          <th className="sr-only">Result</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.field} className={cn("border-t", !c.ok && (c.blocks ? "bg-danger-soft" : "bg-warning-soft"))}>
            <td className="py-2 pr-2">{FIELD_NAME[c.field] ?? humanize(c.field)}</td>
            <td className="py-2 pr-2">{c.expected}</td>
            <td className="py-2 pr-2 font-medium">{c.actual}</td>
            <td className="py-2 text-right">
              {c.ok ? <CheckCircle2 className="inline size-4 text-success" aria-label="matches" /> : <XCircle className={cn("inline size-4", c.blocks ? "text-danger" : "text-warning")} aria-label={c.blocks ? "mismatch, quarantine" : "outside tolerance, flagged"} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ManualLine({ busy, onAdd }: { busy: boolean; onAdd: (body: object) => void }) {
  const [v, setV] = useState({ supplier_lot: "", fibre: "Cotton", count: "", colour: "", label_kg: "", received_kg: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (k: keyof typeof v, value: string) => setV((p) => ({ ...p, [k]: value }));
  function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    for (const k of ["supplier_lot", "fibre", "count", "colour"] as const) if (!v[k].trim()) errs[k] = "Required";
    for (const k of ["label_kg", "received_kg"] as const) if (!KG_RE.test(v[k]) || Number(v[k]) <= 0) errs[k] = "Kilos above 0";
    setErrors(errs);
    if (!Object.keys(errs).length) onAdd({ ...v, supplier_lot: v.supplier_lot.trim(), fibre: v.fibre.trim(), count: v.count.trim(), colour: v.colour.trim() });
  }
  const field = (k: keyof typeof v, label: string, decimal = false) => (
    <FormField name={k} label={label} error={errors[k]} required>
      <Input id={k} value={v[k]} maxLength={60} inputMode={decimal ? "decimal" : undefined} onChange={(e) => set(k, e.target.value)} aria-invalid={!!errors[k]} className="h-11" />
    </FormField>
  );
  return (
    <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2">
      {field("supplier_lot", "Supplier lot")}
      {field("fibre", "Fibre")}
      {field("count", "Count (e.g. Ne 30/1)")}
      {field("colour", "Colour")}
      {field("label_kg", "Kg on label", true)}
      {field("received_kg", "Weighed kg", true)}
      <Button type="submit" size="lg" className="h-12 sm:col-span-2" disabled={busy}>Add lot</Button>
    </form>
  );
}

function MissingLine({ busy, onAdd }: { busy: boolean; onAdd: (body: object) => void }) {
  const [weight, setWeight] = useState("");
  const [error, setError] = useState<string>();
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!KG_RE.test(weight) || Number(weight) <= 0) return setError("Kilos above 0, up to 3 decimals");
    onAdd({ label_missing: true, received_kg: weight });
  }
  return (
    <form onSubmit={submit} noValidate className="grid gap-3">
      <p className="text-sm text-muted-foreground">The lot is held as “pending identification” and never counts as stock until someone identifies it.</p>
      <FormField name="missing_kg" label="Weighed kilos" error={error} required>
        <Input id="missing_kg" inputMode="decimal" value={weight} onChange={(e) => setWeight(e.target.value)} aria-invalid={!!error} className="h-12 text-base md:text-base" />
      </FormField>
      <Button type="submit" size="lg" className="h-12" disabled={busy}>Add unlabelled lot</Button>
    </form>
  );
}

function DeliveryTable({ query }: { query: UseQueryResult<Paged<Delivery>> }) {
  if (query.isError) return <ErrorText error={query.error} />;
  if (query.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (query.data.total === 0) return <p className="text-sm text-muted-foreground">No open deliveries. Add one when a supplier confirms a dispatch.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">Supplier</th>
            <th className="px-3 py-2 font-medium">Yarn</th>
            <th className="px-3 py-2 text-right font-medium">Expected</th>
            <th className="px-3 py-2 text-right font-medium">Received</th>
            <th className="px-3 py-2 font-medium">Due</th>
            <th className="px-3 py-2 font-medium">For order</th>
            <th className="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {query.data.items.map((d) => (
            <tr key={d.id} className="border-t">
              <td className="px-3 py-2 whitespace-nowrap">{d.supplier_name}</td>
              <td className="px-3 py-2 whitespace-nowrap">{d.label}</td>
              <td className="px-3 py-2 text-right">{kg(d.expected_kg)}</td>
              <td className="px-3 py-2 text-right">{kg(d.received_kg)}</td>
              <td className="px-3 py-2">{date(d.expected_date)}</td>
              <td className="px-3 py-2">{d.order_code ?? "—"}</td>
              <td className="px-3 py-2"><StatusBadge status={d.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
