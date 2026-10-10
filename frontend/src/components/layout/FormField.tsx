import type { ReactNode } from "react";

import { Label } from "@/components/ui/label";

// label + control + inline error; the error id is wired to aria-describedby by the caller
export function FormField({
  name,
  label,
  error,
  hint,
  required,
  children,
}: {
  name: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={name}>
        {label}
        {required && <span className="text-danger" aria-hidden>*</span>}
      </Label>
      {children}
      {error ? (
        <p id={`${name}-error`} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : (
        hint && <p className="text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}
