"use client";

import { AlertTriangle, Check, CircleAlert, Minus, Plus, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { type FormEvent, type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { dateTime, humanize, metres } from "@/lib/format";
import { cn } from "@/lib/utils";

import { type Decision, DEFECT_TYPES, type DefectType, type RollDetail, SHADE_BANDS, type ShadeBand, useDecide, useRoll } from "./api";

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

  if (roll.isPending) return <Skeleton className="h-64 w-full" />;
  if (roll.isError) {
    return (
      <EmptyState icon={AlertTriangle} title="Could not load this roll" action={<Button variant="outline" onClick={() => roll.refetch()}>Try again</Button>}>
        {roll.error.message}
      </EmptyState>
    );
  }
  const r = roll.data;

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
          <Link href={`/orders/${r.order_id}`} className="num hover:text-ember">
            {r.order_code}
          </Link>
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
        <p role="status" className="flex items-center gap-2 border border-success bg-success-soft px-3 py-2.5 text-sm font-medium text-success">
          <Check className="size-4 shrink-0" aria-hidden />
          {done}
        </p>
      )}

      {r.status === "awaiting_qc" && <DecisionForm key={`${r.id}-${r.checks.length}`} roll={r} onDone={setDone} />}

      {r.checks.length > 0 && (
        <Section title="QC history">
          <ol className="grid border border-border">
            {r.checks.map((c) => (
              <li key={c.id} className="grid gap-1 border-b border-border px-3 py-2.5 last:border-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="label">Attempt {c.attempt_no}</span>
                  <StatusBadge status={c.decision} />
                  {c.shade_band && <span className="label">Shade {c.shade_band}</span>}
                  <span className="ml-auto text-sm text-muted-foreground">{dateTime(c.at)}</span>
                </div>
                {c.defects.length > 0 && (
                  <p className="text-sm text-body">{c.defects.map((d) => `${humanize(d.type)} × ${d.count}`).join(", ")}</p>
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
    </div>
  );
}

function DecisionForm({ roll, onDone }: { roll: RollDetail; onDone: (message: string) => void }) {
  const decide = useDecide(roll.id);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [defects, setDefects] = useState<Partial<Record<DefectType, number>>>({});
  const [shade, setShade] = useState<ShadeBand | null>(null);
  const [gsm, setGsm] = useState("");
  const [width, setWidth] = useState("");
  const [note, setNote] = useState("");
  const errors = decide.errors;

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
    decide.mutate(
      {
        decision,
        defects: DEFECT_TYPES.filter((t) => defects[t]).map((t) => ({ type: t, count: defects[t]! })),
        shade_band: decision === "pass" ? shade : null,
        gsm: gsm.trim() || null,
        width_cm: width.trim() || null,
        note: note.trim() || null,
      },
      { onSuccess: () => onDone(`${roll.code} ${DONE_TEXT[decision]}.`) },
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
              onClick={() => setDecision(value)}
              className={cn(
                "pressable flex h-20 flex-col items-center justify-center gap-1.5 border font-mono text-[0.8rem] tracking-[0.1em] uppercase outline-none focus-visible:ring-1 focus-visible:ring-ember",
                decision === value ? on : "border-border bg-card text-foreground hover:border-foreground",
              )}
            >
              <Icon className="size-5" aria-hidden />
              {label}
            </button>
          ))}
        </div>
      </Section>

      <Section title="Defects">
        <div className="grid grid-cols-2 gap-2">
          {DEFECT_TYPES.map((t) => {
            const n = defects[t] ?? 0;
            return (
              <div key={t} className={cn("flex items-center justify-between gap-1 border pl-3", n ? "border-ember bg-ember-soft" : "border-border bg-card")}>
                <button type="button" onClick={() => bump(t, n ? -n : 1)} className={cn("min-w-0 truncate py-2 text-left text-sm", n && "text-ember")}>
                  {humanize(t)}
                </button>
                <div className="flex shrink-0 items-center">
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Fewer ${humanize(t)}`} disabled={!n} onClick={() => bump(t, -1)}>
                    <Minus />
                  </Button>
                  <span className="num w-6 text-center text-sm" aria-live="polite">
                    {n}
                  </span>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`More ${humanize(t)}`} onClick={() => bump(t, 1)}>
                    <Plus />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
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
        <FormField name="gsm" label="GSM" error={errors.gsm} hint={`Spec ${Number(roll.fabric_gsm)}`}>
          <Input id="gsm" inputMode="decimal" value={gsm} onChange={(e) => setGsm(e.target.value)} aria-invalid={!!errors.gsm} aria-describedby={errors.gsm ? "gsm-error" : undefined} />
        </FormField>
        <FormField name="width_cm" label="Width (cm)" error={errors.width_cm} hint={`Spec ${Number(roll.fabric_width_cm)}`}>
          <Input id="width_cm" inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)} aria-invalid={!!errors.width_cm} aria-describedby={errors.width_cm ? "width_cm-error" : undefined} />
        </FormField>
      </div>

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
