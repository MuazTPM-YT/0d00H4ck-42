"use client";

import { Select } from "@/components/ui/select";

import { AlertTriangle, Check, CircleAlert, Minus, Plus, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { type FormEvent, type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { dateTime, humanize, kg, metres } from "@/lib/format";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { canSee, findRoute } from "@/nav";
import { validQuantity } from "@/lib/validation";

import { type Decision, DEFECTS, type DefectType, defectLabel, defectPoints, type RollDetail, SHADE_BANDS, type ShadeBand, SIZES, scorePer100, type Stage, useDecide, useQueue, useRoll, useTrace } from "./api";

const DECISIONS: { value: Decision; label: string; icon: typeof Check; on: string }[] = [
  { value: "pass", label: "Pass", icon: Check, on: "border-success bg-success-soft text-success" },
  { value: "rework", label: "Rework", icon: RotateCcw, on: "border-warning bg-warning-soft text-warning" },
  { value: "reject", label: "Reject", icon: X, on: "border-danger bg-danger-soft text-danger" },
];

const DONE_TEXT: Record<Decision, string> = {
  pass: "passed and moved to finished goods",
  rework: "sent back for rework, a rework job is on the floor",
  reject: "rejected and moved to the reject bay",
};

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 border-t border-border pt-2">
      <dt className="label">{label}</dt>
      <dd className="mt-1 truncate">{children}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-3">
      <h3 className="label text-foreground">{title}</h3>
      {children}
    </section>
  );
}

// R10 + R11: who made this roll, what QC said before, and the decision form while it waits
export function RollInspection({ id, compact = false }: { id: number; compact?: boolean }) {
  const roll = useRoll(id);
  const [done, setDone] = useState<string | null>(null);
  // supervisor, dispatch and accounts read the roll; only QC decides (server says the same)
  const role = useMe().data?.role;
  const inspector = role === "qc" || role === "owner";

  if (roll.isPending) return <Skeleton className="h-64 w-full" />;
  if (roll.isError) {
    return (
      <EmptyState icon={AlertTriangle} title="Could not load this roll" action={<Button variant="outline" onClick={() => roll.refetch()}>Try again</Button>}>
        {roll.error.message}
      </EmptyState>
    );
  }
  const r = roll.data;
  const orderRoute = findRoute(`/orders/${r.order_id}`);
  const canOpenOrder = !!role && !!orderRoute && canSee(orderRoute, role);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="num text-[1.4rem]">{r.code}</span>
        <StatusBadge status={r.status} />
        {r.shade_band && <span className="label">Shade {r.shade_band}</span>}
        {compact && (
          <Link href={`/qc/rolls/${r.id}`} className="label ml-auto hover:text-ember">
            Open page
          </Link>
        )}
      </div>

      <dl className={cn("grid gap-x-4 gap-y-3", compact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4")}>
        <Fact label="Order">
          {canOpenOrder ? (
            <Link href={`/orders/${r.order_id}`} className="num hover:text-ember">
              {r.order_code}
            </Link>
          ) : (
            <span className="num">{r.order_code}</span>
          )}
        </Fact>
        <Fact label="Buyer">{r.buyer_name}</Fact>
        <Fact label="Fabric">{r.fabric_name}</Fact>
        <Fact label="Colour">{r.colour}</Fact>
        <Fact label="Loom">
          <span className="num">{r.loom_code}</span>
        </Fact>
        <Fact label="Shift">{r.shift_name}</Fact>
        <Fact label="Weaver">{r.weaver_name ?? "—"}</Fact>
        <Fact label="Length">
          <span className="num">{metres(r.length_m)}</span>
        </Fact>
        <Fact label="Spec">
          <span className="num">
            {Number(r.fabric_gsm)} gsm · {Number(r.fabric_width_cm)} cm
          </span>
        </Fact>
        <Fact label="Last moved">{dateTime(r.waiting_since)}</Fact>
      </dl>

      {done && (
        <div role="status" className="flex flex-wrap items-center gap-2 border border-success bg-success-soft px-3 py-2.5 text-sm font-medium text-success">
          <Check className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">{done}</span>
          {!compact && <NextRoll after={r.id} />}
        </div>
      )}

      {r.status === "awaiting_qc" &&
        (inspector ? (
          <DecisionForm key={`${r.id}-${r.checks.length}`} roll={r} onDone={setDone} />
        ) : (
          <p className="border-t border-foreground pt-5 text-sm text-muted-foreground">Waiting for QC.</p>
        ))}

      {r.checks.length > 0 && (
        <Section title="QC history">
          <ol className="grid border border-border">
            {r.checks.map((c) => (
              <li key={c.id} className="grid gap-1 border-b border-border px-3 py-2.5 last:border-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="label">Attempt {c.attempt_no}</span>
                  <StatusBadge status={c.decision} />
                  {c.shade_band && <span className="label">Shade {c.shade_band}</span>}
                  {c.defects.length > 0 && (
                    <span className="label">
                      {defectPoints(c.defects)} pts · {scorePer100(defectPoints(c.defects), Number(r.length_m), Number(c.width_cm ?? r.fabric_width_cm))} / 100 m²
                    </span>
                  )}
                  <span className="ml-auto text-sm text-muted-foreground">{dateTime(c.at)}</span>
                </div>
                {c.defects.length > 0 && (
                  <p className="text-sm text-body">{c.defects.map((d) => `${defectLabel(d.type)} × ${d.count}`).join(", ")}</p>
                )}
                {(c.gsm || c.width_cm) && (
                  <p className="num text-sm text-muted-foreground">
                    {c.gsm && `${Number(c.gsm)} gsm`}
                    {c.gsm && c.width_cm && " · "}
                    {c.width_cm && `${Number(c.width_cm)} cm`}
                  </p>
                )}
                {c.notes && <p className="text-sm text-body">{c.notes}</p>}
              </li>
            ))}
          </ol>
        </Section>
      )}

      {!compact && <TraceSections id={r.id} />}
    </div>
  );
}

// the oldest other roll still waiting: inspectors work the queue without going back to it
function NextRoll({ after }: { after: number }) {
  const queue = useQueue(0, 2);
  const next = queue.data?.items.find((x) => x.id !== after);
  if (!next) return <Link href="/qc" className="underline underline-offset-4">Back to the queue</Link>;
  return (
    <Link href={`/qc/rolls/${next.id}`} className="underline underline-offset-4">
      Open next roll {next.code}
    </Link>
  );
}

const EVENT_TITLE: Record<string, string> = {
  woven: "Woven",
  dyed: "Dyed",
  rework: "Reworked",
  qc_pass: "QC passed",
  qc_rework: "QC sent to rework",
  qc_reject: "QC rejected",
};

// D3 genealogy: yarn lots and suppliers in the roll, every event, rework jobs, the truck
function TraceSections({ id }: { id: number }) {
  const trace = useTrace(id);
  if (trace.isPending) return <Skeleton className="h-40 w-full" />;
  if (trace.isError) return <p className="text-sm text-danger">Trace did not load: {trace.error.message}</p>;
  const t = trace.data;
  return (
    <>
      <Section title="Yarn in this roll">
        {t.yarn.length === 0 ? (
          <p className="text-sm text-muted-foreground">No yarn lineage recorded for this roll.</p>
        ) : (
          <ul className="grid border border-border">
            {t.yarn.map((y) => (
              <li key={y.batch_id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 border-b border-border px-3 py-2.5 last:border-0">
                <span className="min-w-0">
                  <span className="num font-medium">{y.batch_code}</span> · {y.yarn}
                  <span className="block truncate text-sm text-muted-foreground">
                    {y.supplier_name} · lot {y.supplier_lot ?? "none"}
                  </span>
                </span>
                <span className="num self-center">{kg(y.kg)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Where it has been">
        <ol className="scroll-panel grid max-h-72 border border-border">
          {t.events.map((e, i) => (
            <li key={i} className="grid grid-cols-[8.5rem_1fr] gap-3 border-b border-border px-3 py-2.5 last:border-0">
              <span className="num text-sm text-muted-foreground">{dateTime(e.at)}</span>
              <span>
                <span className="block font-medium">{EVENT_TITLE[e.kind] ?? humanize(e.kind)}</span>
                <span className="block text-sm text-muted-foreground">{[e.machine_code, e.work_order_code, e.note].filter(Boolean).join(" · ") || "—"}</span>
              </span>
            </li>
          ))}
          <li className="grid grid-cols-[8.5rem_1fr] gap-3 px-3 py-2.5">
            <span className="label self-center">Now</span>
            <span>
              {t.roll.location_name} ({t.roll.location_code})
              {t.dispatch && <span className="block text-sm text-muted-foreground">On {t.dispatch.code} · {humanize(t.dispatch.status)}</span>}
            </span>
          </li>
        </ol>
      </Section>
      {t.rework_jobs.length > 0 && (
        <Section title="Rework jobs">
          <ul className="grid border border-border">
            {t.rework_jobs.map((j) => (
              <li key={j.id} className="flex items-center justify-between gap-3 border-b border-border px-3 py-2.5 last:border-0">
                <span>
                  <span className="num font-medium">{j.code}</span>
                  <span className="block text-sm text-muted-foreground">
                    {humanize(j.stage)}
                    {j.machine_code ? ` on ${j.machine_code}` : ", not on a machine yet"}
                  </span>
                </span>
                <StatusBadge status={j.status} />
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

// same rules as the server: rework only for a confirmed order, and not after two checks
const MAX_REWORK_CHECKS = 2;
function reworkBlocked(roll: RollDetail): string | null {
  if (roll.order_status !== "confirmed") return `Order is ${humanize(roll.order_status).toLowerCase()}: reject instead.`;
  if (roll.checks.length >= MAX_REWORK_CHECKS) return "Third check: pass or reject.";
  return null;
}

function DecisionForm({ roll, onDone }: { roll: RollDetail; onDone: (message: string) => void }) {
  const decide = useDecide(roll.id);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [defects, setDefects] = useState<Partial<Record<DefectType, number>>>({});
  const [sizes, setSizes] = useState<Partial<Record<DefectType, number>>>({});
  const [stage, setStage] = useState<Stage | null>(null);
  const [key] = useState(() => crypto.randomUUID());
  const stages = useTrace(roll.id).data?.rework_stages ?? [];
  const [shade, setShade] = useState<ShadeBand | null>(null);
  const [gsm, setGsm] = useState("");
  const [width, setWidth] = useState("");
  const [note, setNote] = useState("");
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  const errors = { ...decide.errors, ...localErrors };
  const picked = DEFECTS.filter((d) => defects[d.type]).map((d) => ({ type: d.type, count: defects[d.type]!, points: d.type === "hole" ? 4 : (sizes[d.type] ?? 1) }));
  const points = defectPoints(picked);
  const score = scorePer100(points, Number(roll.length_m), Number(width) > 0 ? Number(width) : Number(roll.fabric_width_cm));
  // server default: last stage on the route, unless the inspector picks another
  const reworkStage = stage ?? stages.at(-1) ?? null;
  const blocked = reworkBlocked(roll);
  // measured vs spec, signed percent
  const off = (measured: string, spec: string) => (Number(measured) > 0 ? Math.round(((Number(measured) - Number(spec)) / Number(spec)) * 1000) / 10 : null);
  const gsmOff = off(gsm, roll.fabric_gsm);
  const widthOff = off(width, roll.fabric_width_cm);

  const bump = (type: DefectType, by: number) =>
    setDefects((d) => {
      const next = { ...d };
      const n = Math.max(0, Math.min(999, (d[type] ?? 0) + by));
      if (n) next[type] = n;
      else delete next[type];
      return next;
    });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!decision) return;
    const invalid: Record<string, string> = {};
    if (gsm && !validQuantity(gsm, 99999.99, 2, 0.01)) invalid.gsm = "Enter GSM above 0, up to 99,999.99 with at most 2 decimals";
    if (width && !validQuantity(width, 99999.99, 2, 0.01)) invalid.width_cm = "Enter width above 0, up to 99,999.99 with at most 2 decimals";
    if (decision === "pass" && !shade) invalid.shade_band = "Pick a shade band to pass the roll";
    if (decision !== "pass" && !picked.length) invalid.defects = "Mark at least one defect";
    setLocalErrors(invalid);
    if (Object.keys(invalid).length) return;
    decide.mutate(
      {
        decision,
        defects: picked,
        shade_band: decision === "pass" ? shade : null,
        gsm: gsm.trim() || null,
        width_cm: width.trim() || null,
        note: note.trim() || null,
        rework_stage: decision === "rework" ? reworkStage : null,
        idempotency_key: key,
      },
      { onSuccess: (res) => onDone(`${roll.code} ${DONE_TEXT[decision]}.${res.dispatch_code ? ` Order covered: truck ${res.dispatch_code} drafted for dispatch.` : ""}`) },
    );
  };

  return (
    <form onSubmit={submit} className="grid gap-5 border-t border-foreground pt-5" noValidate>
      <Section title="Decision">
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Decision">
          {DECISIONS.map(({ value, label, icon: Icon, on }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={decision === value}
              disabled={value === "rework" && !!blocked}
              title={value === "rework" ? (blocked ?? undefined) : undefined}
              onClick={() => setDecision(value)}
              className={cn(
                "pressable flex h-20 flex-col items-center justify-center gap-1.5 border text-[0.95rem] font-semibold outline-none focus-visible:ring-1 focus-visible:ring-ember disabled:cursor-not-allowed disabled:opacity-40",
                decision === value ? on : "border-border bg-card text-foreground hover:border-foreground",
              )}
            >
              <Icon className="size-5" aria-hidden />
              {label}
            </button>
          ))}
        </div>
        {blocked && <p className="text-[0.82rem] text-muted-foreground">Rework not offered. {blocked}</p>}
      </Section>

      <Section title="Defects">
        <p className="-mt-1 flex justify-between gap-3 text-sm text-muted-foreground">
          <span>4-point system: each fault scores by its length.</span>
          <span className="num shrink-0 text-foreground">
            {points} {points === 1 ? "pt" : "pts"}{score !== null && points > 0 ? ` · ${score} / 100 m²` : ""}
          </span>
        </p>
        <ul className="grid border border-border">
          {DEFECTS.map(({ type, label, hint }) => {
            const n = defects[type] ?? 0;
            return (
              <li key={type} className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2 last:border-0", n > 0 && "bg-ember-soft")}>
                <span className="min-w-0">
                  <span className={cn("block font-medium", n > 0 && "text-ember")}>{label}</span>
                  <span className="block truncate text-[0.8rem] text-muted-foreground">{hint}</span>
                </span>
                <span className="flex items-center">
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Fewer ${label}`} disabled={!n} onClick={() => bump(type, -1)}>
                    <Minus />
                  </Button>
                  <span className="num w-8 text-center" aria-live="polite">
                    {n}
                  </span>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`More ${label}`} onClick={() => bump(type, 1)}>
                    <Plus />
                  </Button>
                </span>
                {n > 0 && type !== "hole" && (
                  <Select aria-label={`${label} length`} value={sizes[type] ?? 1} onChange={(e) => setSizes((v) => ({ ...v, [type]: Number(e.target.value) }))} className="col-span-2 h-10 border border-input px-3 text-sm">
                    {SIZES.map((sz) => (
                      <option key={sz.points} value={sz.points}>
                        {sz.label} · {sz.points} {sz.points === 1 ? "point" : "points"} each
                      </option>
                    ))}
                  </Select>
                )}
              </li>
            );
          })}
        </ul>
        {errors.defects && (
          <p role="alert" className="flex items-start gap-1.5 text-[0.88rem] font-medium text-danger">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {errors.defects}
          </p>
        )}
      </Section>

      {decision === "pass" && (
        <Section title="Shade band">
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Shade band" aria-describedby={errors.shade_band ? "shade_band-error" : undefined}>
            {SHADE_BANDS.map((b) => (
              <button
                key={b}
                type="button"
                role="radio"
                aria-checked={shade === b}
                onClick={() => setShade(b)}
                className={cn(
                  "pressable num h-12 border text-lg outline-none focus-visible:ring-1 focus-visible:ring-ember",
                  shade === b ? "border-foreground bg-foreground text-background" : "border-border bg-card hover:border-foreground",
                )}
              >
                {b}
              </button>
            ))}
          </div>
          {errors.shade_band ? (
            <p id="shade_band-error" role="alert" className="flex items-start gap-1.5 text-[0.88rem] font-medium text-danger">
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {errors.shade_band}
            </p>
          ) : (
            <p className="text-[0.82rem] text-muted-foreground">Required to pass. Dispatch keeps one band per load.</p>
          )}
        </Section>
      )}

      <div className="grid grid-cols-2 gap-3">
        <FormField name="gsm" label="GSM" error={errors.gsm} hint={gsmOff === null ? `Spec ${Number(roll.fabric_gsm)}` : `${gsmOff > 0 ? "+" : ""}${gsmOff}% vs spec ${Number(roll.fabric_gsm)}`}>
          <Input id="gsm" inputMode="decimal" value={gsm} onChange={(e) => setGsm(e.target.value)} aria-invalid={!!errors.gsm} aria-describedby={errors.gsm ? "gsm-error" : undefined} />
        </FormField>
        <FormField name="width_cm" label="Width (cm)" error={errors.width_cm} hint={widthOff === null ? `Spec ${Number(roll.fabric_width_cm)}` : `${widthOff > 0 ? "+" : ""}${widthOff}% vs spec ${Number(roll.fabric_width_cm)}`}>
          <Input id="width_cm" inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)} aria-invalid={!!errors.width_cm} aria-describedby={errors.width_cm ? "width_cm-error" : undefined} />
        </FormField>
      </div>

      {decision === "rework" && stages.length > 1 && (
        <FormField name="rework_stage" label="Redo at" error={errors.rework_stage} hint="The rework job lands on the supervisor's work orders. The roll comes back here after it.">
          <Select id="rework_stage" value={reworkStage ?? ""} onChange={(e) => setStage(e.target.value as Stage)} className="h-11 w-full border border-input px-3">
            {stages.map((st) => (
              <option key={st} value={st}>
                {humanize(st)}
              </option>
            ))}
          </Select>
        </FormField>
      )}

      <FormField name="note" label="Note" error={errors.note}>
        <Input id="note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="What you saw, where on the roll" />
      </FormField>

      {errors.form && (
        <p role="alert" className="flex items-center gap-2 border border-danger bg-danger-soft px-3 py-2.5 text-sm font-medium text-danger">
          <CircleAlert className="size-4 shrink-0" aria-hidden />
          {errors.form}
        </p>
      )}

      <Button type="submit" size="lg" disabled={!decision || (decision === "pass" && !shade) || decide.isPending}>
        {decide.isPending ? "Saving…" : decision ? `Record ${DECISIONS.find((d) => d.value === decision)!.label.toLowerCase()}` : "Pick a decision"}
      </Button>
    </form>
  );
}
