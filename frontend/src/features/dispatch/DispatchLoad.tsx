"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, Copy, Mail, MessageCircle, Phone, Printer, RefreshCw, ScanLine, Truck, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, type SubmitEvent, useRef, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { CameraScan } from "@/components/layout/CameraScan";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { dateTime, metres } from "@/lib/format";
import { copyText } from "@/lib/share";
import { useSSE } from "@/lib/useSSE";
import { cn } from "@/lib/utils";
import { PrintArea } from "@/features/finance/PrintArea";

import { CodeForm, type DeliverBody } from "./CodeForm";
import { VEHICLE_RE } from "./DispatchList";
import type { DispatchDetail, LoadedRoll, ScanResult } from "./types";

type Feedback = { ok: boolean; text: string } | null;

// tablet loading screen: scan (or type) a roll code, watch the count, confirm when the truck is full
export function DispatchLoad({ id }: { id: string }) {
  useSSE(["dispatch"]);
  const qc = useQueryClient();
  const role = useMe().data?.role;
  const key = ["dispatch", "detail", id];
  const detail = useQuery({ queryKey: key, queryFn: () => api<DispatchDetail>(`/dispatch/dispatches/${id}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["dispatch"] });

  if (detail.isPending) return <Skeleton className="h-96 w-full" />;
  if (detail.isError) {
    return (
      <EmptyState icon={AlertTriangle} title="Could not load this dispatch" action={<Button variant="outline" onClick={() => detail.refetch()}>Try again</Button>}>
        {detail.error.message}
      </EmptyState>
    );
  }
  const d = detail.data;
  const clerk = role === "dispatch" || role === "owner";
  const open = d.status !== "confirmed";

  return (
    <>
      <PageHeader
        title={`${d.code} · ${d.order_code}`}
        description={`${d.buyer_name} · ${d.fabric}, ${d.colour}`}
        actions={<StatusBadge status={d.status} className="text-sm" />}
      />
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Ordered" value={metres(d.ordered_m)} />
        <Stat label="Shipped earlier" value={metres(d.shipped_m)} />
        <Stat label="On this truck" value={`${d.loaded.length} rolls · ${metres(d.loaded_m)}`} strong />
        <Stat label={open ? "Still to load" : "Left after this"} value={metres(d.remaining_m)} />
      </div>

      {open ? (
        <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
          <div className="grid content-start gap-6">
            {clerk && <ScanBox id={id} onScanned={refresh} />}
            <RollLists d={d} id={id} clerk={clerk} onChange={refresh} />
          </div>
          <div className="grid content-start gap-6">
            {clerk && <VehicleForm d={d} id={id} onSaved={refresh} />}
            <ShadePanel d={d} id={id} canOverride={role === "owner" || role === "supervisor"} onSaved={refresh} />
            {clerk && <ConfirmButton d={d} id={id} onDone={refresh} />}
            {clerk && <CancelTruck d={d} id={id} />}
          </div>
        </div>
      ) : (
        <div className="grid gap-6">
          <DeliveryPanel d={d} id={id} clerk={clerk} onChange={refresh} />
          <Challan d={d} />
        </div>
      )}
    </>
  );
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={cn("rounded-lg border bg-card p-4", strong && "border-primary")}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular">{value}</div>
    </div>
  );
}

// scanner types the code and presses enter; a person can type it too
function ScanBox({ id, onScanned }: { id: string; onScanned: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const scan = useMutation({
    mutationFn: (code: string) =>
      api<ScanResult>(`/dispatch/dispatches/${id}/scan`, { method: "POST", json: { roll_code: code, idempotency_key: crypto.randomUUID() } }),
    onSuccess: (r) => {
      setFeedback({ ok: true, text: `${r.roll_code} loaded · ${r.roll_count} rolls · ${metres(r.loaded_m)} · ${metres(r.remaining_m)} to go` });
      onScanned();
    },
    onError: (err) => setFeedback({ ok: false, text: err.message }),
    onSettled: () => {
      if (input.current) input.current.value = "";
      input.current?.focus();
    },
  });

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = input.current?.value.trim().toUpperCase() ?? "";
    if (!code) return setFeedback({ ok: false, text: "Scan or type a roll code" });
    scan.mutate(code);
  }

  return (
    <form onSubmit={submit} data-tour="truck-scan" className="rounded-lg border bg-card p-4">
      <label htmlFor="roll_code" className="mb-2 flex items-center gap-2 font-medium">
        <ScanLine className="size-5" aria-hidden /> Scan roll onto truck
      </label>
      <div className="flex gap-2">
        <Input ref={input} id="roll_code" name="roll_code" autoFocus autoComplete="off" maxLength={20} placeholder="R-000123" className="h-14 text-lg uppercase" />
        <CameraScan onScan={(code) => scan.mutate(code.toUpperCase())} disabled={scan.isPending} />
        <Button type="submit" size="lg" className="h-14 px-6" disabled={scan.isPending}>Load</Button>
      </div>
      {feedback && (
        <p role="status" className={cn("mt-3 flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium", feedback.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger")}>
          {feedback.ok ? <CheckCircle2 className="size-4 shrink-0" /> : <AlertTriangle className="size-4 shrink-0" />}
          {feedback.text}
        </p>
      )}
    </form>
  );
}

function RollLists({ d, id, clerk, onChange }: { d: DispatchDetail; id: string; clerk: boolean; onChange: () => void }) {
  const [error, setError] = useState("");
  const proposed = new Set(d.proposal?.roll_ids ?? []);
  const load = useMutation({
    mutationFn: (code: string) => api(`/dispatch/dispatches/${id}/scan`, { method: "POST", json: { roll_code: code, idempotency_key: crypto.randomUUID() } }),
    onSuccess: () => { setError(""); onChange(); },
    onError: (err) => setError(err.message),
  });
  const unload = useMutation({
    mutationFn: (rollId: number) => api(`/dispatch/dispatches/${id}/rolls/${rollId}`, { method: "DELETE" }),
    onSuccess: () => { setError(""); onChange(); },
    onError: (err) => setError(err.message),
  });
  const p = d.proposal;

  return (
    <>
      <section className="rounded-lg border bg-card">
        <h2 className="border-b px-4 py-3 font-medium">On the truck ({d.loaded.length})</h2>
        {d.loaded.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">Nothing loaded yet. Scan the first roll.</p>
        ) : (
          <RollTable rolls={d.loaded} action={clerk ? (r) => (
            <Button variant="outline" size="lg" aria-label={`Take ${r.code} off`} onClick={() => unload.mutate(r.id)} disabled={unload.isPending}><X /> Off</Button>
          ) : undefined} />
        )}
      </section>
      <section className="rounded-lg border bg-card">
        <div className="border-b px-4 py-3">
          <h2 className="font-medium">Ready on the shelf ({d.candidates.length})</h2>
          {p && (
            <p className="mt-1 text-sm text-muted-foreground">
              Suggested: {p.roll_ids.length} rolls of shade {p.band ?? "—"} = {metres(p.total_m)} for {metres(p.need_m)} needed
              {Number(p.short_m) > 0 ? `, ${metres(p.short_m)} short` : `, ${metres(p.overshoot_m)} over`}.
            </p>
          )}
        </div>
        {d.candidates.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">No more passed rolls of this order on the shelf.</p>
        ) : (
          <RollTable rolls={d.candidates} highlight={proposed} action={clerk ? (r) => (
            <Button variant={proposed.has(r.id) ? "default" : "outline"} size="lg" onClick={() => load.mutate(r.code)} disabled={load.isPending}>Load</Button>
          ) : undefined} />
        )}
      </section>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </>
  );
}

function RollTable({ rolls, action, highlight }: { rolls: LoadedRoll[]; action?: (r: LoadedRoll) => ReactNode; highlight?: Set<number> }) {
  return (
    <ul className="divide-y">
      {rolls.map((r) => (
        <li key={r.id} className={cn("flex items-center gap-3 px-4 py-2", highlight?.has(r.id) && "bg-info-soft")}>
          <div className="min-w-0 flex-1">
            <div className="font-medium">
              {r.code}
              {highlight?.has(r.id) && <span className="ml-2 text-xs text-info">suggested</span>}
            </div>
            <div className="text-xs text-muted-foreground">{r.location} · shade {r.shade_band ?? "—"}</div>
          </div>
          <div className="tabular">{metres(r.length_m)}</div>
          {action?.(r)}
        </li>
      ))}
    </ul>
  );
}

function VehicleForm({ d, id, onSaved }: { d: DispatchDetail; id: string; onSaved: () => void }) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: (body: { vehicle_no: string; driver: string | null; driver_email: string | null }) => api(`/dispatch/dispatches/${id}/vehicle`, { method: "PUT", json: body }),
    onSuccess: () => { setSaved(true); onSaved(); },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });
  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrors({});
    setSaved(false);
    if (!e.currentTarget.checkValidity()) return;
    const f = new FormData(e.currentTarget);
    save.mutate({
      vehicle_no: String(f.get("vehicle_no")).trim(),
      driver: String(f.get("driver") ?? "").trim() || null,
      driver_email: String(f.get("driver_email") ?? "").trim() || null,
    });
  }
  return (
    <form noValidate onSubmit={submit} onInvalidCapture={(e) => {
      const el = e.target as HTMLInputElement;
      setErrors((p) => ({ ...p, [el.name]: el.validity.patternMismatch ? el.title : el.validationMessage }));
    }} className="grid gap-3 rounded-lg border bg-card p-4">
      <h2 className="flex items-center gap-2 font-medium"><Truck className="size-5" aria-hidden /> Vehicle</h2>
      <FormField name="vehicle_no" label="Vehicle no." required error={errors.vehicle_no}>
        <Input id="vehicle_no" name="vehicle_no" required defaultValue={d.vehicle_no ?? ""} maxLength={20} pattern={VEHICLE_RE} title="Letters, digits, spaces or dashes, 5 to 20 long" className="h-12 text-base uppercase" aria-invalid={!!errors.vehicle_no} />
      </FormField>
      <FormField name="driver" label="Driver" error={errors.driver}>
        <Input id="driver" name="driver" defaultValue={d.driver ?? ""} maxLength={120} className="h-12 text-base" />
      </FormField>
      <FormField name="driver_email" label="Driver email" error={errors.driver_email} hint="Optional: the driver link is emailed when the truck leaves">
        <Input id="driver_email" name="driver_email" type="email" defaultValue={d.driver_email ?? ""} maxLength={254} className="h-12 text-base" aria-invalid={!!errors.driver_email} />
      </FormField>
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <Button type="submit" variant="outline" size="lg" disabled={save.isPending}>{saved ? <><Check /> Saved</> : "Save vehicle"}</Button>
    </form>
  );
}

// one shade per truck; a supervisor (or owner) can allow a mix with a written reason
function ShadePanel({ d, id, canOverride, onSaved }: { d: DispatchDetail; id: string; canOverride: boolean; onSaved: () => void }) {
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: (reason: string) => api(`/dispatch/dispatches/${id}/shade-override`, { method: "POST", json: { reason } }),
    onSuccess: () => { setError(""); onSaved(); },
    onError: (err) => setError(err.message),
  });
  return (
    <section className="grid gap-2 rounded-lg border bg-card p-4 text-sm">
      <h2 className="font-medium">Shade</h2>
      <p>{d.bands.length ? `Truck carries shade ${d.bands.join(", ")}.` : "No shade fixed yet: the first roll sets it."}</p>
      {d.shade_override ? (
        <p className="rounded-md bg-warning-soft px-3 py-2 text-warning">Mixed shades allowed: {d.shade_override}</p>
      ) : canOverride ? (
        <form noValidate onSubmit={(e) => {
          e.preventDefault();
          const reason = String(new FormData(e.currentTarget).get("reason") ?? "").trim();
          if (!reason) return setError("Write why mixing shades is fine for this buyer");
          save.mutate(reason);
        }} className="grid gap-2">
          <FormField name="reason" label="Allow mixed shades because" error={error}>
            <Input id="reason" name="reason" maxLength={2000} placeholder="Buyer agreed on call" aria-invalid={!!error} />
          </FormField>
          <Button type="submit" variant="outline" disabled={save.isPending}>Allow mixed shades</Button>
        </form>
      ) : (
        <p className="text-muted-foreground">A roll of another shade needs a supervisor override.</p>
      )}
    </section>
  );
}

function ConfirmButton({ d, id, onDone }: { d: DispatchDetail; id: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const confirm = useMutation({
    mutationFn: () => api(`/dispatch/dispatches/${id}/confirm`, { method: "POST" }),
    onSuccess: () => { setOpen(false); onDone(); },
  });
  const ready = d.status === "loading" && d.loaded.length > 0;
  return (
    <>
      <Button size="lg" className="h-14 text-base" disabled={!ready} onClick={() => { confirm.reset(); setOpen(true); }}>
        <Truck /> Confirm and invoice
      </Button>
      {!ready && <p className="text-sm text-muted-foreground">Load at least one roll first.</p>}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Truck leaves now?</DialogTitle>
            <DialogDescription>
              {d.loaded.length} rolls, {metres(d.loaded_m)} to {d.buyer_name} on {d.vehicle_no ?? "no vehicle yet"}. The invoice is made from exactly these rolls and cannot be edited.
            </DialogDescription>
          </DialogHeader>
          {confirm.isError && <p role="alert" className="text-sm text-danger">{confirm.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="lg" onClick={() => setOpen(false)}>Back</Button>
            <Button size="lg" onClick={() => confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending ? "Confirming…" : "Confirm dispatch"}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// truck not going after all: rolls go back on the shelf, the draft disappears
function CancelTruck({ d, id }: { d: DispatchDetail; id: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const cancel = useMutation({
    mutationFn: () => api(`/dispatch/dispatches/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dispatch"] });
      router.push("/dispatch");
    },
  });
  return (
    <>
      <Button variant="outline" size="lg" className="text-danger" onClick={() => { cancel.reset(); setOpen(true); }}>
        <X /> Cancel truck
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Cancel {d.code}?</DialogTitle>
            <DialogDescription>
              {d.loaded.length ? `${d.loaded.length} rolls (${metres(d.loaded_m)}) go back on the shelf.` : "Nothing is loaded."} The dispatch is removed; no invoice is made.
            </DialogDescription>
          </DialogHeader>
          {cancel.isError && <p role="alert" className="text-sm text-danger">{cancel.error.message}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="lg" onClick={() => setOpen(false)}>Keep truck</Button>
            <Button variant="destructive" size="lg" onClick={() => cancel.mutate()} disabled={cancel.isPending}>{cancel.isPending ? "Cancelling…" : "Cancel truck"}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// same link as the driver email; this browser's address only when WEB_URL is unset
function driverUrl(d: DispatchDetail): string {
  if (d.delivery_url) return d.delivery_url;
  return typeof window === "undefined" || !d.delivery_token ? "" : `${window.location.origin}/deliver/${d.delivery_token}`;
}

// after the gate: share the driver link; the buyer's code, typed by the driver, closes the trip.
// staff never see the code, they can only issue a new one
function DeliveryPanel({ d, id, clerk, onChange }: { d: DispatchDetail; id: string; clerk: boolean; onChange: () => void }) {
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const [phone, setPhone] = useState(false);
  const url = driverUrl(d);
  const message = `Delivery ${d.code} to ${d.buyer_name}${d.buyer_city ? `, ${d.buyer_city}` : ""}: ${d.loaded.length} rolls. At the gate, count the rolls with the buyer, ask for their delivery code and enter it here: ${url}`;
  const newCode = useMutation({
    mutationFn: () => api(`/dispatch/dispatches/${id}/new-code`, { method: "POST" }),
    onSuccess: onChange,
  });
  const deliver = useMutation({
    mutationFn: (body: DeliverBody) => api(`/dispatch/dispatches/${id}/deliver`, { method: "POST", json: body }),
    onSuccess: () => { setPhone(false); onChange(); },
    // a wrong code spends a try: refresh so the count shows
    onError: onChange,
  });
  async function onCopy() {
    setCopy((await copyText(url)) ? "copied" : "failed");
    setTimeout(() => setCopy("idle"), 2000);
  }

  if (d.delivered_at) {
    return (
      <section className="grid gap-1 rounded-lg border border-success bg-success-soft p-4 text-sm text-success">
        <div className="flex items-center gap-2 font-medium"><CheckCircle2 className="size-4" aria-hidden /> Delivered {dateTime(d.delivered_at)}</div>
        <div>Received by {d.received_by}</div>
        {d.delivery_note && <div>Note: {d.delivery_note}</div>}
      </section>
    );
  }
  const locked = d.has_code && d.tries_left === 0;
  return (
    <section className="grid gap-3 rounded-lg border bg-card p-4 text-sm">
      <h2 className="flex items-center gap-2 font-medium"><Truck className="size-5" aria-hidden /> On the way · driver link</h2>
      <p className="break-all text-muted-foreground">{url}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onCopy}>
          {copy === "copied" ? <Check /> : <Copy />} {copy === "copied" ? "Copied" : "Copy link"}
        </Button>
        <Button variant="outline" size="sm" asChild>
          <a href={`https://wa.me/?text=${encodeURIComponent(message)}`} target="_blank" rel="noopener noreferrer" title="Pick the driver in WhatsApp">
            <MessageCircle /> WhatsApp
          </a>
        </Button>
        {clerk && (
          <Button variant="outline" size="sm" onClick={() => { deliver.reset(); setPhone((v) => !v); }}>
            <Phone /> Driver called with code
          </Button>
        )}
        {clerk && (
          <Button variant="outline" size="sm" disabled={newCode.isPending} onClick={() => window.confirm("The buyer link shows a new code and the old one stops working. Continue?") && newCode.mutate()}>
            <RefreshCw /> New code
          </Button>
        )}
      </div>
      {locked ? (
        <p role="alert" className="bg-warning-soft px-3 py-2 text-warning">Code locked after 5 wrong tries. Press New code, then ask the buyer to read the new one from their order link.</p>
      ) : !d.has_code ? (
        <p role="alert" className="bg-warning-soft px-3 py-2 text-warning">No delivery code yet. Press New code.</p>
      ) : (
        <p className="text-muted-foreground">The buyer sees the delivery code on their order link and gives it to the driver after counting the rolls. {d.tries_left} {d.tries_left === 1 ? "try" : "tries"} left.</p>
      )}
      {copy === "failed" && <p role="alert" className="text-danger">Could not copy. Select the link above and copy it by hand.</p>}
      {newCode.isError && <p role="alert" className="text-danger">{newCode.error.message}</p>}
      {d.mail_on && <DriverMail d={d} id={id} clerk={clerk} onChange={onChange} />}
      {phone && clerk && (
        <div className="border-t pt-3">
          <CodeForm label="Mark delivered" onSubmit={(b) => deliver.mutate(b)} pending={deliver.isPending} error={deliver.error} disabled={locked || !d.has_code} />
        </div>
      )}
    </section>
  );
}

// was the driver link emailed? clerk can resend, or fill in a missing or wrong address
function DriverMail({ d, id, clerk, onChange }: { d: DispatchDetail; id: string; clerk: boolean; onChange: () => void }) {
  const [error, setError] = useState("");
  const send = useMutation({
    mutationFn: (driver_email: string | null) => api(`/dispatch/dispatches/${id}/email-driver`, { method: "POST", json: { driver_email } }),
    onSuccess: () => { setError(""); onChange(); },
    onError: (err) => setError(err.message),
  });
  const m = d.driver_mail;
  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("driver_email_again") as HTMLInputElement;
    if (!input.checkValidity()) return setError("Enter a valid email address");
    send.mutate(input.value.trim() || null);
  }
  return (
    <div className="grid gap-2 border-t pt-3">
      {!m ? (
        <p className="text-muted-foreground">Driver link not emailed yet.</p>
      ) : m.status === "sent" ? (
        <p className="text-success">Driver link emailed to {m.to} on {dateTime(m.at)}.</p>
      ) : m.status === "skipped" ? (
        <p className="text-warning">Driver link not emailed: no driver email on this truck.</p>
      ) : (
        <p role="alert" className="text-danger">Driver link email to {m.to} failed on {dateTime(m.at)}: {m.error}</p>
      )}
      {clerk && (
        <form noValidate onSubmit={submit} className="flex flex-wrap gap-2">
          <Input name="driver_email_again" type="email" aria-label="Driver email" defaultValue={d.driver_email ?? ""} maxLength={254} placeholder="driver@example.com" className="h-9 min-w-0 flex-1" aria-invalid={!!error} />
          <Button type="submit" variant="outline" size="sm" disabled={send.isPending}>
            <Mail /> {send.isPending ? "Sending…" : m?.status === "sent" ? "Resend to driver" : "Email driver"}
          </Button>
        </form>
      )}
      {error && <p role="alert" className="text-danger">{error}</p>}
    </div>
  );
}

// delivery challan: what physically left, roll by roll
function Challan({ d }: { d: DispatchDetail }) {
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => window.print()}><Printer /> Print challan</Button>
        {d.invoice_id && <Button variant="outline" asChild><Link href={`/finance/invoices?open=${d.invoice_id}`}>Invoice {d.invoice_code}</Link></Button>}
      </div>
      <PrintArea>
        <div className="mb-4 flex flex-wrap justify-between gap-4">
          <div>
            <div className="text-lg font-semibold">Everest Textile Mills</div>
            <div className="text-muted-foreground">Delivery challan {d.code}</div>
          </div>
          <div className="text-right">
            <div>Date: {dateTime(d.confirmed_at)}</div>
            <div>Vehicle: {d.vehicle_no} {d.driver && `· ${d.driver}`}</div>
          </div>
        </div>
        <div className="mb-4">
          <div className="font-medium">{d.buyer_name}</div>
          <div className="text-muted-foreground">GSTIN {d.buyer_gstin}{d.buyer_city && ` · ${d.buyer_city}`}</div>
          <div>Order {d.order_code} · {d.fabric}, {d.colour}</div>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b text-left"><th className="py-1">#</th><th>Roll</th><th>Shade</th><th className="text-right">Metres</th></tr>
          </thead>
          <tbody>
            {d.loaded.map((r, i) => (
              <tr key={r.id} className="border-b"><td className="py-1">{i + 1}</td><td>{r.code}</td><td>{r.shade_band ?? "—"}</td><td className="text-right tabular">{metres(r.length_m)}</td></tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="font-semibold"><td className="py-1" colSpan={3}>{d.loaded.length} rolls</td><td className="text-right tabular">{metres(d.loaded_m)}</td></tr>
          </tfoot>
        </table>
        <div className="mt-10 grid grid-cols-2 gap-8 text-muted-foreground">
          <div className="border-t pt-1">Dispatched by</div>
          <div className="border-t pt-1">Received by{d.received_by && `: ${d.received_by}, ${dateTime(d.delivered_at)}`}</div>
        </div>
        {d.delivery_token && !d.delivered_at && (
          <p className="mt-6 break-all text-xs text-muted-foreground">
            Driver: at the buyer&apos;s gate open {driverUrl(d)} and enter the buyer&apos;s delivery code.
          </p>
        )}
      </PrintArea>
    </div>
  );
}
