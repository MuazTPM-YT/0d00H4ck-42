import type { ReactNode } from "react";

import { CircleAlert } from "lucide-react";

import { Label } from "@/components/ui/label";

// label + control + inline error; the error id is wired to aria-describedby by the caller.
// Pinned to the top, so a taller neighbour (one with a hint) never pushes this label down
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
    <div className="grid min-w-0 content-start gap-2">
      <Label htmlFor={name}>
        {label}
        {required && <span className="text-danger" aria-hidden>*</span>}
      </Label>
      {children}
      {error ? (
        <p id={`${name}-error`} role="alert" className="flex items-start gap-1.5 text-[0.88rem] font-medium text-danger">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      ) : (
        hint && <p className="text-[0.82rem] text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}
