"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type SubmitEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { humanize, inr, paiseToRupees, rupeesToPaise } from "@/lib/format";

import { PAYMENT_MODES, SELECT } from "./types";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

// buyer money against one invoice; the server decides part paid or paid
export function PaymentForm({ invoiceId, outstanding, onDone }: { invoiceId: number; outstanding: number; onDone?: () => void }) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (body: object) => api("/finance/payments", { method: "POST", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      onDone?.();
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrors({});
    const form = e.currentTarget;
    if (!form.checkValidity()) return;
    const f = new FormData(form);
    const paise = rupeesToPaise(String(f.get("amount")));
    if (paise === null || paise <= 0) return setErrors({ amount_paise: "Enter rupees, e.g. 25000 or 25000.50" });
    if (paise > outstanding) return setErrors({ amount_paise: `Only ${inr(outstanding)} is outstanding` });
    save.mutate({
      invoice_id: invoiceId,
      amount_paise: paise,
      received_on: f.get("received_on"),
      mode: f.get("mode"),
      ref: String(f.get("ref") ?? "").trim() || null,
    });
  }

  return (
    <form noValidate onSubmit={submit} onInvalidCapture={(e) => {
      const el = e.target as HTMLInputElement;
      setErrors((p) => ({ ...p, [el.name === "amount" ? "amount_paise" : el.name]: el.validationMessage }));
    }} className="grid gap-3 sm:grid-cols-2">
      <FormField name="amount" label="Amount (₹)" required error={errors.amount_paise}>
        <Input id="amount" name="amount" inputMode="decimal" required defaultValue={paiseToRupees(outstanding)} aria-invalid={!!errors.amount_paise} />
      </FormField>
      <FormField name="received_on" label="Received on" required error={errors.received_on}>
        <Input id="received_on" name="received_on" type="date" required max={today()} defaultValue={today()} aria-invalid={!!errors.received_on} />
      </FormField>
      <FormField name="mode" label="Mode" required error={errors.mode}>
        <select id="mode" name="mode" required className={SELECT} defaultValue="bank_transfer">
          {PAYMENT_MODES.map((m) => <option key={m} value={m}>{humanize(m)}</option>)}
        </select>
      </FormField>
      <FormField name="ref" label="Reference" error={errors.ref} hint="UTR, cheque no.">
        <Input id="ref" name="ref" maxLength={60} />
      </FormField>
      {(errors.form || errors.invoice_id) && <p role="alert" className="text-sm text-danger sm:col-span-2">{errors.form ?? errors.invoice_id}</p>}
      <Button type="submit" className="sm:col-span-2" disabled={save.isPending}>{save.isPending ? "Saving…" : "Record payment"}</Button>
    </form>
  );
}
