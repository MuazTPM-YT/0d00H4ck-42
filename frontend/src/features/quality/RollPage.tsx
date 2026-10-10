"use client";

import { AlertTriangle, Minus, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useMemo, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError, type Paged } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { date, dateTime, humanize, kg, metres } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSSE } from "@/lib/useSSE";

import { type Decision, DECISION_LABEL, DEFECTS, type QueueRow, scorePer100, SIZES, type Stage, type Trace, useInspect, useTrace } from "./api";
import { defectsText } from "./QcHome";

const DECISION_STYLE: Record<Decision, string> = {
  pass: "border-success bg-success text-white",
  rework: "border-warning bg-warning text-white",
  reject: "border-danger bg-danger text-white",
};
const SUBMIT: Record<Decision, string> = { pass: "Pass roll", rework: "Send to rework", reject: "Reject roll" };

// how far a measured figure sits from the fabric spec, signed, one decimal
const deviation = (measured: string, spec: string) => {
  const m = Number(measured);
  return measured.trim() && m > 0 ? Math.round(((m - Number(spec)) / Number(spec)) * 1000) / 10 : null;
};

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 className="text-base">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-2.5 px-4 py-4 text-[0.94rem]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="label self-center">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// the rework job goes where the fault can be fixed: colour faults to dyeing, cloth faults to the loom
function defaultStage(stages: Stage[], types: string[]): Stage | "" {
  if (stages.includes("dyeing") && types.some((t) => t === "colour_mismatch" || t === "stain")) return "dyeing";
  return stages.includes("weaving") ? "weaving" : (stages.at(-1) ?? "");
}

function InspectForm({ t }: { t: Trace }) {
  const router = useRouter();
  const inspect = useInspect(t.roll.id);
  const [key] = useState(() => crypto.randomUUID());
  const [decision, setDecision] = useState<Decision>("pass");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [sizes, setSizes] = useState<Record<string, number>>({});
  const [shade, setShade] = useState("");
  const [gsm, setGsm] = useState("");
  const [width, setWidth] = useState("");
  const [notes, setNotes] = useState("");
  const [stage, setStage] = useState<Stage | "">("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const defects = DEFECTS.filter((d) => (counts[d.type] ?? 0) > 0).map((d) => ({
    type: d.type,
    count: counts[d.type],
    points: d.type === "hole" ? 4 : (sizes[d.type] ?? 1),
  }));
  const points = defects.reduce((s, d) => s + d.count * d.points, 0);
  const widthCm = Number(width) > 0 ? Number(width) : Number(t.fabric.width_cm);
  const score = scorePer100(points, Number(t.roll.length_m), widthCm);
  const gsmDev = deviation(gsm, t.fabric.gsm);
  const widthDev = deviation(width, t.fabric.width_cm);
  const reworkStage = stage || defaultStage(t.rework_stages, defects.map((d) => d.type));

  const bump = (type: string, by: number) => setCounts((c) => ({ ...c, [type]: Math.max(0, Math.min(999, (c[type] ?? 0) + by)) }));

  function submit(e: { preventDefault: () => void }) {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (decision === "pass") {
      if (!shade) local.shade_band = "Pick the shade band";
      if (!(Number(gsm) > 0)) local.gsm = "Enter the GSM you weighed";
      if (!(Number(width) > 0)) local.width_cm = "Enter the width you measured";
    } else if (defects.length === 0) local.defects = `Mark at least one defect to ${decision} this roll`;
    setErrors(local);
    if (Object.keys(local).length) return;
    inspect.mutate(
      {
        decision,
        defects,
        shade_band: decision === "pass" ? shade : undefined,
        gsm: gsm.trim() || undefined,
        width_cm: width.trim() || undefined,
        notes: notes.trim() || undefined,
        rework_stage: decision === "rework" && reworkStage ? reworkStage : undefined,
        idempotency_key: key,
      },
      {
        onSuccess: async (res) => {
          const what = `${res.roll_code} ${res.status === "passed" ? "passed" : res.status === "rework" ? `sent to rework (${res.rework_work_order_code})` : "rejected"}`;
          const queue = await api<Paged<QueueRow>>("/quality/queue?limit=200").catch(() => ({ items: [] as QueueRow[], total: 0 }));
          const next = queue.items.find((r) => r.id !== res.roll_id);
          router.push(next ? `/qc/rolls/${next.id}?done=${encodeURIComponent(what)}` : `/qc?done=${encodeURIComponent(what)}`);
        },
        onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
      },
    );
  }

  return (
    <Section title="Inspect this roll" aside={<span className="label">Check {t.checks.length + 1}</span>}>
      <form className="grid gap-6 p-4" onSubmit={submit} noValidate>
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Decision">
          {(["pass", "rework", "reject"] as Decision[]).map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={decision === d}
              onClick={() => setDecision(d)}
              className={cn("pressable h-14 border text-[1rem] font-semibold", decision === d ? DECISION_STYLE[d] : "border-input bg-card hover:border-foreground")}
            >
              {DECISION_LABEL[d]}
            </button>
          ))}
        </div>

        <fieldset className="grid gap-2">
          <legend className="mb-2 flex w-full items-baseline justify-between gap-3">
            <span className="text-[0.88rem] font-semibold">Defects found</span>
            <span className="num text-[0.85rem] text-muted-foreground">
              {points} pts{score !== null && ` · ${score} per 100 m²`}
            </span>
          </legend>
          <ul className="grid border border-border">
            {DEFECTS.map((d) => {
              const n = counts[d.type] ?? 0;
              return (
                <li key={d.type} className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0 sm:grid-cols-[minmax(0,1fr)_11rem_auto]", n > 0 && "bg-accent/60")}>
                  <span className="min-w-0">
                    <span className="block font-medium">{d.label}</span>
                    <span className="block truncate text-[0.8rem] text-muted-foreground">{d.hint}</span>
                  </span>
                  {d.type === "hole" ? (
                    <span className="label hidden sm:block">4 points each</span>
                  ) : (
                    <select aria-label={`${d.label} size`} value={sizes[d.type] ?? 1} disabled={n === 0} onChange={(e) => setSizes((s) => ({ ...s, [d.type]: Number(e.target.value) }))} className="col-span-2 row-start-2 h-10 border border-input px-3 text-sm disabled:opacity-50 sm:col-span-1 sm:row-start-auto">
                      {SIZES.map((sz) => (
                        <option key={sz.points} value={sz.points}>
                          {sz.label} · {sz.points} pt
                        </option>
                      ))}
                    </select>
                  )}
                  <span className="flex items-center">
                    <Button type="button" variant="outline" size="icon-sm" aria-label={`One less ${d.label}`} disabled={n === 0} onClick={() => bump(d.type, -1)}>
                      <Minus />
                    </Button>
                    <span className="num w-10 text-center text-lg font-medium" aria-live="polite">
                      {n}
                    </span>
                    <Button type="button" variant="outline" size="icon-sm" aria-label={`One more ${d.label}`} onClick={() => bump(d.type, 1)}>
                      <Plus />
                    </Button>
                  </span>
                </li>
              );
            })}
          </ul>
          {errors.defects && (
            <p role="alert" className="text-sm font-medium text-danger">
              {errors.defects}
            </p>
          )}
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField name="gsm" label="GSM measured" required={decision === "pass"} error={errors.gsm} hint={gsmDev === null ? `Spec ${Number(t.fabric.gsm)} g/m²` : `${gsmDev > 0 ? "+" : ""}${gsmDev}% vs spec ${Number(t.fabric.gsm)}`}>
            <Input id="gsm" inputMode="decimal" value={gsm} onChange={(e) => setGsm(e.target.value)} aria-invalid={!!errors.gsm} className={cn(gsmDev !== null && Math.abs(gsmDev) > 5 && "border-warning")} />
          </FormField>
          <FormField name="width_cm" label="Width measured (cm)" required={decision === "pass"} error={errors.width_cm} hint={widthDev === null ? `Spec ${Number(t.fabric.width_cm)} cm` : `${widthDev > 0 ? "+" : ""}${widthDev}% vs spec ${Number(t.fabric.width_cm)}`}>
            <Input id="width_cm" inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)} aria-invalid={!!errors.width_cm} className={cn(widthDev !== null && widthDev < -1 && "border-warning")} />
          </FormField>
        </div>

        {decision === "pass" && (
          <fieldset>
            <legend className="mb-2 text-[0.88rem] font-semibold">
              Shade band <span className="text-danger">*</span>
            </legend>
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Shade band">
              {["A", "B", "C"].map((b) => (
                <button key={b} type="button" role="radio" aria-checked={shade === b} onClick={() => setShade(b)} className={cn("pressable h-12 border font-mono text-lg font-medium", shade === b ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card hover:border-foreground")}>
                  {b}
                </button>
              ))}
            </div>
            {errors.shade_band ? (
              <p role="alert" className="mt-1.5 text-sm font-medium text-danger">
                {errors.shade_band}
              </p>
            ) : (
              <p className="mt-1.5 text-[0.82rem] text-muted-foreground">Rolls of one band ship together, so a buyer never gets two shades in one delivery.</p>
            )}
          </fieldset>
        )}

        {decision === "rework" && t.rework_stages.length > 0 && (
          <FormField name="rework_stage" label="Redo at" error={errors.rework_stage} hint="A rework job lands on the supervisor's work orders. The roll comes back here after it.">
            <select id="rework_stage" value={reworkStage} onChange={(e) => setStage(e.target.value as Stage)} className="h-11 w-full border border-input px-3">
              {t.rework_stages.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </select>
          </FormField>
        )}

        <FormField name="notes" label="Notes" error={errors.notes} hint="Where on the roll, what you saw. Kept with the check.">
          <textarea id="notes" rows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} className="w-full border border-input px-3 py-2 text-base outline-none focus-visible:border-ember" />
        </FormField>

        {errors.form && (
          <p role="alert" className="border border-danger/40 bg-danger-soft px-4 py-3 text-sm font-medium text-danger">
            {errors.form}
          </p>
        )}
        <Button type="submit" size="lg" disabled={inspect.isPending} className={cn(decision !== "pass" && (decision === "reject" ? "bg-danger hover:bg-danger/90" : "bg-warning hover:bg-warning/90"))}>
          {inspect.isPending ? "Saving…" : `${SUBMIT[decision]} and open next`}
        </Button>
      </form>
    </Section>
  );
}

// R10, R11, D3: one roll, where it came from, every check on it, and the inspection form
export function RollPage({ id }: { id: number }) {
  useSSE(["quality"]);
  const trace = useTrace(id);
  const role = useMe().data?.role;
  const done = useSearchParams().get("done");
  const history = useMemo(() => {
    const t = trace.data;
    if (!t) return [];
    const rows: { at: string; title: string; detail: string }[] = t.events.map((e) => ({
      at: e.at,
      title: e.kind === "woven" ? "Woven" : e.kind === "dyed" ? "Dyed" : e.kind === "rework" ? "Reworked" : humanize(e.kind),
      detail: [e.machine_code, e.work_order_code, e.note].filter(Boolean).join(" · "),
    }));
    for (const c of t.checks) rows.push({ at: c.at, title: `QC ${DECISION_LABEL[c.decision].toLowerCase()} (check ${c.attempt_no})`, detail: `${c.inspector_name} · ${defectsText(c)}` });
    return rows.sort((a, b) => a.at.localeCompare(b.at));
  }, [trace.data]);

  if (trace.isError)
    return (
      <EmptyState icon={AlertTriangle} title="Could not load this roll" action={<Button variant="outline" onClick={() => trace.refetch()}>Try again</Button>}>
        {trace.error.message}
      </EmptyState>
    );
  if (trace.isPending) return <Skeleton className="h-[32rem] w-full" />;
  const t = trace.data;
  const canInspect = t.roll.status === "awaiting_qc" && (role === "qc" || role === "owner");
  const last = t.checks.at(-1);

  return (
    <>
      <PageHeader title={t.roll.code} description={`${t.order.code} · ${t.order.buyer_name} · ${t.fabric.name}, ${t.order.colour}`} actions={<StatusBadge status={t.roll.status} className="text-[0.8rem]" />} />
      {done && (
        <p role="status" className="mb-5 border border-success/40 bg-success-soft px-4 py-3 text-[0.94rem] font-medium text-success">
          {done}. Next roll in the queue is open.
        </p>
      )}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="grid min-w-0 grid-cols-1 gap-6">
          {canInspect ? (
            <InspectForm key={t.roll.id} t={t} />
          ) : (
            t.roll.status === "awaiting_qc" && (
              <p className="border border-border bg-card px-4 py-3 text-[0.94rem] text-muted-foreground">This roll is waiting for QC. Only a QC inspector can record the check.</p>
            )
          )}

          <Section title={`Checks (${t.checks.length})`}>
            {t.checks.length === 0 ? (
              <p className="px-4 py-5 text-sm text-muted-foreground">Not checked yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>When</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead>Defects</TableHead>
                    <TableHead className="text-right">Pts / 100 m²</TableHead>
                    <TableHead>GSM · width</TableHead>
                    <TableHead>By</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {t.checks.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="num">{c.attempt_no}</TableCell>
                      <TableCell className="num">{dateTime(c.at)}</TableCell>
                      <TableCell>
                        <StatusBadge status={c.decision} />
                        {c.shade_band && <span className="num ml-2">Band {c.shade_band}</span>}
                      </TableCell>
                      <TableCell className="whitespace-normal">
                        {defectsText(c)}
                        {c.notes && <span className="block text-[0.82rem] text-muted-foreground">{c.notes}</span>}
                      </TableCell>
                      <TableCell className="num text-right">{c.score ?? "—"}</TableCell>
                      <TableCell className="num">{c.gsm ? `${Number(c.gsm)} · ${Number(c.width_cm)} cm` : "—"}</TableCell>
                      <TableCell>{c.inspector_name}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>

          <Section title="Yarn in this roll" aside={<span className="label">{t.yarn.length} lots</span>}>
            {t.yarn.length === 0 ? (
              <p className="px-4 py-5 text-sm text-muted-foreground">No yarn lineage recorded for this roll.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Batch</TableHead>
                    <TableHead>Yarn</TableHead>
                    <TableHead>Supplier · lot</TableHead>
                    <TableHead className="text-right">Used</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {t.yarn.map((y) => (
                    <TableRow key={y.batch_id}>
                      <TableCell className="num font-medium">{y.batch_code}</TableCell>
                      <TableCell>{y.yarn}</TableCell>
                      <TableCell>
                        {y.supplier_name} <span className="num text-muted-foreground">· {y.supplier_lot ?? "no lot"}</span>
                      </TableCell>
                      <TableCell className="num text-right">{kg(y.kg)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>

          <Section title="History">
            <ol className="scroll-panel grid max-h-80 gap-0 px-4 py-2">
              {history.map((h, i) => (
                <li key={i} className="grid grid-cols-[8.5rem_1fr] gap-3 border-b border-border py-2.5 last:border-0">
                  <span className="num text-[0.82rem] text-muted-foreground">{dateTime(h.at)}</span>
                  <span>
                    <span className="block font-medium">{h.title}</span>
                    {h.detail && <span className="block text-[0.85rem] text-muted-foreground">{h.detail}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </Section>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:sticky lg:top-6">
          <Section title="Roll">
            <Facts
              rows={[
                ["Length", <span key="l" className="num">{metres(t.roll.length_m)}</span>],
                ["Location", `${t.roll.location_name} (${t.roll.location_code})`],
                ["Shade band", t.roll.shade_band ?? "—"],
                ["Passed", t.roll.passed_at ? dateTime(t.roll.passed_at) : "—"],
                ["Last check", last ? `${DECISION_LABEL[last.decision]} · ${last.points} pts` : "—"],
                ["Dispatch", t.dispatch ? `${t.dispatch.code} (${humanize(t.dispatch.status)})` : "—"],
              ]}
            />
          </Section>
          <Section title="Made by">
            <Facts
              rows={[
                ["Order", <Link key="o" href={`/orders/${t.order.id}`} className="font-medium hover:text-ember">{t.order.code}</Link>],
                ["Buyer", t.order.buyer_name],
                ["Deadline", date(t.order.deadline)],
                ["Fabric", `${t.fabric.name} · ${Number(t.fabric.gsm)} GSM · ${Number(t.fabric.width_cm)} cm`],
                ["Route", t.fabric.route.map(humanize).join(" → ")],
                ["Loom", `${t.loom.code} · ${t.loom.name}`],
                ["Shift", t.shift.name],
                ["Weaver", t.weaver ? `${t.weaver.name} (${t.weaver.code})` : "Not recorded"],
              ]}
            />
          </Section>
          {t.rework_jobs.length > 0 && (
            <Section title="Rework jobs">
              <ul className="grid gap-0 px-4 py-2">
                {t.rework_jobs.map((j) => (
                  <li key={j.id} className="flex items-center justify-between gap-3 border-b border-border py-2.5 last:border-0">
                    <span>
                      <span className="num block font-medium">{j.code}</span>
                      <span className="block text-[0.82rem] text-muted-foreground">
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
        </div>
      </div>
    </>
  );
}
