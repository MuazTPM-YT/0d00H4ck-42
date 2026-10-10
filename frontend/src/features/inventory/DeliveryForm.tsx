"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { paiseToRupees, rupeesToPaise } from "@/lib/format";

import { selectClass, useMaster, type NamedOption, type YarnItemOption } from "./ui";

export type DeliveryPrefill = {
  yarn_item_id?: number | null;
  supplier_id?: number | null;
  expected_kg?: string;
  rate_paise_per_kg?: number | null;
  order_id?: number | null;
  order_code?: string;
};

const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

// what a supplier is sending; used by store on receive and by sales from the to-buy list
export function DeliveryForm({ prefill = {}, onDone }: { prefill?: DeliveryPrefill; onDone: () => void }) {
  const qc = useQueryClient();
  const suppliers = useMaster<NamedOption>("suppliers");
  const items = useMaster<YarnItemOption>("yarn-items");
  const [v, setV] = useState({
    supplier_id: prefill.supplier_id ? String(prefill.supplier_id) : "",
    yarn_item_id: prefill.yarn_item_id ? String(prefill.yarn_item_id) : "",
    expected_kg: prefill.expected_kg ?? "",
    rate: paiseToRupees(prefill.rate_paise_per_kg ?? null),
    expected_date: inDays(3),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (k: keyof typeof v, value: string) => setV((p) => ({ ...p, [k]: value }));

  const save = useMutation({
    mutationFn: (body: object) => api("/inventory/expected-deliveries", { method: "POST", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stock"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      onDone();
    },
    onError: (e) => setErrors({ [e instanceof ApiError && e.field ? fieldFor(e.field) : "form"]: e.message }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!v.supplier_id) errs.supplier_id = "Pick the supplier";
    if (!v.yarn_item_id) errs.yarn_item_id = "Pick the yarn";
    if (!/^\d+(\.\d{1,3})?$/.test(v.expected_kg) || Number(v.expected_kg) <= 0) errs.expected_kg = "Kilos above 0, up to 3 decimals";
    const paise = rupeesToPaise(v.rate);
    if (!paise) errs.rate = "Rupees per kg above 0, e.g. 285 or 285.50";
    if (!v.expected_date) errs.expected_date = "Pick a date";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    save.mutate({
      supplier_id: Number(v.supplier_id),
      yarn_item_id: Number(v.yarn_item_id),
      expected_kg: v.expected_kg,
      rate_paise_per_kg: paise,
      expected_date: v.expected_date,
      order_id: prefill.order_id ?? null,
    });
  }

  const a11y = (name: string) => ({ "aria-invalid": !!errors[name], "aria-describedby": errors[name] ? `${name}-error` : undefined });

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      {prefill.order_code && <p className="text-sm text-muted-foreground">Tagged to order {prefill.order_code}: approved yarn is reserved for it automatically.</p>}
      <FormField name="supplier_id" label="Supplier" error={errors.supplier_id} required>
        <select id="supplier_id" value={v.supplier_id} onChange={(e) => set("supplier_id", e.target.value)} className={selectClass} {...a11y("supplier_id")}>
          <option value="">Choose…</option>
          {suppliers.data?.items.map((s) => (
            <option key={s.id} value={s.id}>{`${s.code} · ${s.name}`}</option>
          ))}
        </select>
      </FormField>
      <FormField name="yarn_item_id" label="Yarn" error={errors.yarn_item_id} required>
        <select id="yarn_item_id" value={v.yarn_item_id} onChange={(e) => set("yarn_item_id", e.target.value)} className={selectClass} {...a11y("yarn_item_id")}>
          <option value="">Choose…</option>
          {items.data?.items.map((i) => (
            <option key={i.id} value={i.id}>{`${i.fibre} ${i.count} ${i.colour}`}</option>
          ))}
        </select>
      </FormField>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField name="expected_kg" label="Kilos" error={errors.expected_kg} required>
          <Input id="expected_kg" inputMode="decimal" value={v.expected_kg} onChange={(e) => set("expected_kg", e.target.value)} {...a11y("expected_kg")} />
        </FormField>
        <FormField name="rate" label="Rate (₹ per kg)" error={errors.rate} required>
          <Input id="rate" inputMode="decimal" value={v.rate} onChange={(e) => set("rate", e.target.value)} {...a11y("rate")} />
        </FormField>
      </div>
      <FormField name="expected_date" label="Expected on" error={errors.expected_date} required>
        <Input id="expected_date" type="date" value={v.expected_date} onChange={(e) => set("expected_date", e.target.value)} {...a11y("expected_date")} />
      </FormField>
      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
        <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save expected delivery"}</Button>
      </DialogFooter>
    </form>
  );
}

// server field names -> the form's own names
const fieldFor = (f: string) => (f === "rate_paise_per_kg" ? "rate" : f);
