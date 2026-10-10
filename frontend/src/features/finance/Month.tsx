"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus } from "lucide-react";
import Link from "next/link";
import { type SubmitEvent, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, qs } from "@/lib/api";
import { date, humanize, inr, kg, metres, rupeesToPaise } from "@/lib/format";
import { cn } from "@/lib/utils";

import { type MachineProduction, type MonthKind, type MonthRecord, type MonthView, SELECT } from "./types";

const thisMonth = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7);
const CATEGORIES = ["power", "maintenance", "transport", "rent", "other"];
const LABEL: Record<MonthKind, string> = {
  invoiced: "Invoices raised",
  received: "Payments received",
  yarn_bills: "Yarn bills",
  wages: "Wage runs",
  expenses: "Other expenses",
};

// did the mill make money this month: both ways, every number opens its records (R23)
export function Month() {
  const [month, setMonth] = useState(thisMonth());
  const [drill, setDrill] = useState<MonthKind | null>(null);
  const [adding, setAdding] = useState(false);
  const view = useQuery({ queryKey: ["finance", "month", month], queryFn: () => api<MonthView>(`/finance/month${qs({ month })}`) });

  return (
    <>
      <PageHeader
        title="Month-end"
        description="Money in, money out and the result, on invoiced and on cash basis."
        actions={
          <>
            <Input aria-label="Month" type="month" value={month} max={thisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} className="w-40" />
            <Button onClick={() => setAdding(true)}><Plus /> Expense</Button>
          </>
        }
      />
      {view.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : view.isError ? (
        <EmptyState icon={AlertTriangle} title="Could not load the month" action={<Button variant="outline" onClick={() => view.refetch()}>Try again</Button>}>{view.error.message}</EmptyState>
      ) : (
        <MonthCards v={view.data} onDrill={setDrill} />
      )}

      <MachineTable month={month} />

      <Dialog open={drill !== null} onOpenChange={(o) => !o && setDrill(null)}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{drill && LABEL[drill]}</DialogTitle>
            <DialogDescription>The records behind the number, for {month}.</DialogDescription>
          </DialogHeader>
          {drill && <Records month={month} kind={drill} />}
        </DialogContent>
      </Dialog>
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add expense</DialogTitle>
            <DialogDescription>Power, maintenance, transport, rent and other running costs.</DialogDescription>
          </DialogHeader>
          {adding && <ExpenseForm onDone={() => setAdding(false)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function MonthCards({ v, onDrill }: { v: MonthView; onDrill: (k: MonthKind) => void }) {
  const Row = ({ label, paise, kind, sign }: { label: string; paise: number; kind: MonthKind; sign?: "-" }) => (
    <button type="button" onClick={() => onDrill(kind)} className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left hover:bg-accent">
      <span>{label}</span>
      <span className="tabular underline decoration-dotted underline-offset-4">{sign}{inr(paise)}</span>
    </button>
  );
  const Result = ({ label, paise }: { label: string; paise: number }) => (
    <div className="flex items-center justify-between border-t px-2 pt-3 font-semibold">
      <span>{label}</span>
      <span className={cn("tabular text-lg", paise >= 0 ? "text-success" : "text-danger")}>{inr(paise)}</span>
    </div>
  );
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border bg-card p-4">
          <h2 className="mb-1 font-medium">Invoiced basis</h2>
          <p className="mb-3 text-xs text-muted-foreground">What was earned and owed this month</p>
          <Row label="Sales invoiced (before GST)" paise={v.invoiced_ex_gst_paise} kind="invoiced" />
          <Row label="Yarn bills" paise={v.yarn_bills_paise} kind="yarn_bills" sign="-" />
          <Row label="Wages (final + paid runs)" paise={v.wages_accrued_paise} kind="wages" sign="-" />
          <Row label="Other expenses" paise={v.expenses_paise} kind="expenses" sign="-" />
          <Result label="Result" paise={v.result_invoiced_paise} />
        </section>
        <section className="rounded-lg border bg-card p-4">
          <h2 className="mb-1 font-medium">Cash basis</h2>
          <p className="mb-3 text-xs text-muted-foreground">Money that actually came in and went out</p>
          <Row label="Received from buyers" paise={v.received_paise} kind="received" />
          <Row label="Yarn bills" paise={v.yarn_bills_paise} kind="yarn_bills" sign="-" />
          <Row label="Wages paid out" paise={v.wages_paid_paise} kind="wages" sign="-" />
          <Row label="Other expenses" paise={v.expenses_paise} kind="expenses" sign="-" />
          <Result label="Result" paise={v.result_cash_paise} />
        </section>
      </div>
      <ul className="list-disc pl-5 text-xs text-muted-foreground">
        <li>Invoices including GST: {inr(v.invoiced_paise)}.</li>
        {v.notes.map((n) => <li key={n}>{n}</li>)}
      </ul>
    </div>
  );
}

function Records({ month, kind }: { month: string; kind: MonthKind }) {
  const rows = useQuery({ queryKey: ["finance", "records", month, kind], queryFn: () => api<MonthRecord[]>(`/finance/month/records${qs({ month, kind })}`) });
  if (rows.isPending) return <Skeleton className="h-40 w-full" />;
  if (rows.isError) return <EmptyState icon={AlertTriangle} title="Could not load records">{rows.error.message}</EmptyState>;
  if (rows.data.length === 0) return <EmptyState title="No records this month" />;
  return (
    <ul className="divide-y rounded-md border text-sm">
      {rows.data.map((r, i) => (
        <li key={i} className="flex flex-wrap items-center gap-3 px-3 py-2">
          <span className="w-24 text-muted-foreground">{date(r.on)}</span>
          <span className="min-w-0 flex-1">{r.link ? <Link href={r.link} className="text-primary hover:underline">{r.ref}</Link> : humanize(r.ref)}<span className="block text-xs text-muted-foreground">{r.party}</span></span>
          <span className="tabular">{inr(r.amount_paise)}</span>
        </li>
      ))}
      <li className="flex justify-between px-3 py-2 font-semibold"><span>Total</span><span className="tabular">{inr(rows.data.reduce((s, r) => s + r.amount_paise, 0))}</span></li>
    </ul>
  );
}

function ExpenseForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (body: object) => api("/finance/expenses", { method: "POST", json: body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance"] }); onDone(); },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });
  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrors({});
    const form = e.currentTarget;
    if (!form.checkValidity()) return;
    const f = new FormData(form);
    const paise = rupeesToPaise(String(f.get("amount")));
    if (!paise) return setErrors({ amount_paise: "Enter rupees above zero, e.g. 1850 or 1850.50" });
    save.mutate({ date: f.get("date"), category: f.get("category"), amount_paise: paise, note: String(f.get("note") ?? "").trim() || null });
  }
  return (
    <form noValidate onSubmit={submit} onInvalidCapture={(e) => {
      const el = e.target as HTMLInputElement;
      setErrors((p) => ({ ...p, [el.name === "amount" ? "amount_paise" : el.name]: el.validationMessage }));
    }} className="grid gap-3">
      <FormField name="date" label="Date" required error={errors.date}>
        <Input id="date" name="date" type="date" required max={new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })} aria-invalid={!!errors.date} />
      </FormField>
      <FormField name="category" label="Category" required error={errors.category}>
        <select id="category" name="category" required className={SELECT} defaultValue="">
          <option value="" disabled>Choose</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
        </select>
      </FormField>
      <FormField name="amount" label="Amount (₹)" required error={errors.amount_paise}>
        <Input id="amount" name="amount" inputMode="decimal" required aria-invalid={!!errors.amount_paise} />
      </FormField>
      <FormField name="note" label="Note" error={errors.note}>
        <Input id="note" name="note" maxLength={2000} />
      </FormField>
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <Button type="submit" disabled={save.isPending}>Save expense</Button>
    </form>
  );
}

// metres (or kg) per machine this month, and where its hours went (R22)
function MachineTable({ month }: { month: string }) {
  const rows = useQuery({ queryKey: ["machines", "production", month], queryFn: () => api<MachineProduction[]>(`/finance/machine-production${qs({ month })}`) });
  return (
    <section className="mt-8 rounded-lg border bg-card">
      <h2 className="border-b px-4 py-3 font-medium">Production per machine</h2>
      {rows.isPending ? (
        <Skeleton className="m-4 h-32" />
      ) : rows.isError ? (
        <p className="px-4 py-6 text-sm text-danger">{rows.error.message}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-normal">Machine</th><th className="text-right font-normal">Output</th><th className="text-right font-normal">Best day</th>
                <th className="text-right font-normal">Running h</th><th className="text-right font-normal">Idle h</th><th className="px-4 text-right font-normal">Breakdown h</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((m) => {
                const best = m.days.reduce<{ day: string; qty: string } | null>((b, d) => (!b || Number(d.qty) > Number(b.qty) ? d : b), null);
                const fmt = m.unit === "kg" ? kg : metres;
                return (
                  <tr key={m.machine_id} className="border-t">
                    <td className="px-4 py-2"><span className="font-medium">{m.code}</span> <span className="text-muted-foreground">{m.name}</span></td>
                    <td className="text-right tabular">{fmt(m.month_qty)}</td>
                    <td className="text-right tabular">{best ? `${fmt(best.qty)} on ${date(best.day)}` : "—"}</td>
                    <td className="text-right tabular">{m.hours.running}</td>
                    <td className="text-right tabular">{m.hours.idle}</td>
                    <td className={cn("px-4 text-right tabular", Number(m.hours.breakdown) > 0 && "font-semibold text-danger")}>{m.hours.breakdown}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
