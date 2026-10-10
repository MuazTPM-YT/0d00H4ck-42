"use client";

import { useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { paiseToRupees, rupeesToPaise } from "@/lib/format";

import type { Field, Master, Row } from "./config";
import { useMasterForm } from "./useMasterForm";

type Values = Record<string, string | boolean>;

const selectClass =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive";

function initial(fields: Field[], row: Row | null): Values {
  return Object.fromEntries(
    fields.map((f) => {
      const v = row?.[f.name];
      if (f.kind === "bool") return [f.name, row ? Boolean(v) : true];
      if (f.kind === "money") return [f.name, paiseToRupees(v as number | null)];
      if (f.kind === "time") return [f.name, typeof v === "string" ? v.slice(0, 5) : ""];
      if (f.kind === "select") return [f.name, (v as string) ?? f.options![0].value];
      return [f.name, v === null || v === undefined ? "" : String(v)];
    }),
  );
}

// form values (strings) -> API body: money to paise, blanks to null, hidden fields to null
function toBody(master: Master, values: Values) {
  const body: Record<string, unknown> = {};
  for (const f of master.fields) {
    const v = values[f.name];
    const shown = !f.showWhen || f.showWhen(values);
    if (f.kind === "bool") body[f.name] = v;
    else if (!shown || v === "") body[f.name] = null;
    else if (f.kind === "money") body[f.name] = rupeesToPaise(v as string);
    else body[f.name] = typeof v === "string" ? v.trim() : v;
  }
  return { ...body, ...master.derive?.(values) };
}

export function MasterForm({ master, row, onDone }: { master: Master; row: Row | null; onDone: () => void }) {
  const [values, setValues] = useState<Values>(() => initial(master.fields, row));
  const { errors, save, formProps, submit } = useMasterForm(master.path, row?.id ?? null, onDone);
  const set = (name: string, v: string | boolean) => setValues((prev) => ({ ...prev, [name]: v }));

  return (
    <form {...formProps} onSubmit={(e) => submit(e, () => toBody(master, values))} className="grid gap-4">
      {master.fields
        .filter((f) => !f.showWhen || f.showWhen(values))
        .map((f) => {
          const err = errors[f.name];
          const a11y = { "aria-invalid": !!err, "aria-describedby": err ? `${f.name}-error` : undefined };
          if (f.kind === "bool") {
            return (
              <label key={f.name} className="flex items-center gap-2 text-sm">
                <input type="checkbox" name={f.name} checked={values[f.name] as boolean} onChange={(e) => set(f.name, e.target.checked)} className="size-4 accent-primary" />
                {f.label}
              </label>
            );
          }
          return (
            <FormField key={f.name} name={f.name} label={f.label} error={err} hint={f.hint} required={f.required}>
              {f.kind === "select" ? (
                <select id={f.name} name={f.name} required={f.required} value={values[f.name] as string} onChange={(e) => set(f.name, e.target.value)} className={selectClass} {...a11y}>
                  {f.options!.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              ) : (
                <Input
                  id={f.name}
                  name={f.name}
                  type={f.kind === "money" ? "text" : f.kind}
                  inputMode={f.kind === "money" ? "decimal" : undefined}
                  pattern={f.kind === "money" ? "\\d+(\\.\\d{1,2})?" : f.pattern}
                  title={f.kind === "money" ? "Rupees, up to 2 decimals, e.g. 650 or 4.50" : f.hint}
                  required={f.required}
                  maxLength={f.maxLength}
                  min={f.min}
                  max={f.max}
                  step={f.step}
                  value={values[f.name] as string}
                  onChange={(e) => set(f.name, e.target.value)}
                  {...a11y}
                />
              )}
            </FormField>
          );
        })}
      {errors.form && (
        <p role="alert" className="text-sm text-danger">
          {errors.form}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : row ? "Save changes" : `Add ${master.singular}`}
        </Button>
      </DialogFooter>
    </form>
  );
}
