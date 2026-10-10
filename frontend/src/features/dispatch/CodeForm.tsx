"use client";

import { type SubmitEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";

export type DeliverBody = { otp: string; received_by: string; note: string | null };

const AREA =
  "w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive md:text-sm";

// buyer's 6-digit code + who signed for it; same form on the driver link and the office phone path
export function CodeForm({
  onSubmit,
  pending,
  error,
  disabled,
  label,
}: {
  onSubmit: (body: DeliverBody) => void;
  pending: boolean;
  error: Error | null;
  disabled?: boolean;
  label: string;
}) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const server: Record<string, string> = error ? { [error instanceof ApiError && error.field ? error.field : "form"]: error.message } : {};
  const shown = { ...server, ...errors };

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const otp = String(f.get("otp") ?? "").trim();
    const received_by = String(f.get("received_by") ?? "").trim();
    const note = String(f.get("note") ?? "").trim();
    const found: Record<string, string> = {};
    if (!/^\d{6}$/.test(otp)) found.otp = "Enter the 6-digit code from the buyer";
    if (!received_by) found.received_by = "Write who received the rolls";
    setErrors(found);
    if (Object.keys(found).length === 0) onSubmit({ otp, received_by, note: note || null });
  }

  return (
    <form noValidate onSubmit={submit} className="grid gap-3">
      <FormField name="otp" label="Delivery code" required error={shown.otp} hint="The buyer reads it from their order link">
        <Input
          id="otp"
          name="otp"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          placeholder="000000"
          className="h-14 font-mono text-2xl tracking-[0.3em]"
          aria-invalid={!!shown.otp}
          aria-describedby={shown.otp ? "otp-error" : undefined}
          disabled={disabled}
        />
      </FormField>
      <FormField name="received_by" label="Received by" required error={shown.received_by}>
        <Input
          id="received_by"
          name="received_by"
          maxLength={80}
          placeholder="Name at the buyer's gate"
          className="h-12 text-base"
          aria-invalid={!!shown.received_by}
          aria-describedby={shown.received_by ? "received_by-error" : undefined}
          disabled={disabled}
        />
      </FormField>
      <FormField name="note" label="Note" error={shown.note} hint="Optional: wet, torn or missing rolls">
        <textarea id="note" name="note" rows={2} maxLength={500} className={AREA} aria-invalid={!!shown.note} disabled={disabled} />
      </FormField>
      {shown.form && <p role="alert" className="text-sm text-danger">{shown.form}</p>}
      <Button type="submit" size="lg" className="h-14 text-base" disabled={pending || disabled}>
        {pending ? "Checking…" : label}
      </Button>
    </form>
  );
}
