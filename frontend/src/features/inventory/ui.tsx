"use client";

import { useQuery } from "@tanstack/react-query";
import { ScanLine } from "lucide-react";
import { type KeyboardEvent, useState } from "react";

import { CameraScan } from "@/components/layout/CameraScan";
import { Input } from "@/components/ui/input";
import { apiAll } from "@/lib/api";
import { cn } from "@/lib/utils";

// small pieces shared by the store and order screens

export const selectClass =
  "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive";

type Option = { id: number; [key: string]: unknown };

// active rows of one master list, for dropdowns
export function useMaster<T extends Option>(path: "suppliers" | "buyers" | "yarn-items" | "fabric-types") {
  return useQuery({
    queryKey: ["masters", path, "options"],
    queryFn: () => apiAll<T>(`/masters/${path}?active=true`),
    staleTime: 60_000,
  });
}

export type YarnItemOption = { id: number; fibre: string; count: string; colour: string; reorder_level_kg: string };
export type NamedOption = { id: number; code: string; name: string };

// USB / Bluetooth scanners type the code and press Enter; people can type too
export function ScanField({
  id,
  label,
  placeholder,
  onScan,
  disabled,
  autoFocus,
  camera,
}: {
  id: string;
  label: string;
  placeholder: string;
  onScan: (value: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  // QR labels only: offer the tablet camera next to the field
  camera?: boolean;
}) {
  const [value, setValue] = useState("");
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // scanners end a code with Enter, or with Tab when set up for spreadsheets
    if (e.key !== "Enter" && !(e.key === "Tab" && value.trim())) return;
    e.preventDefault();
    const v = value.trim();
    if (v) onScan(v);
    setValue("");
  }
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <ScanLine className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            id={id}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            maxLength={300}
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            autoFocus={autoFocus}
            className="h-12 pl-11 text-base md:text-base"
          />
        </div>
        {camera && <CameraScan onScan={onScan} disabled={disabled} />}
      </div>
      <p className="text-xs text-muted-foreground">{camera ? "Scan, use the camera, or type and press Enter." : "Scan, or type and press Enter."}</p>
    </div>
  );
}

const LEVEL = {
  ok: { text: "OK", cls: "bg-success-soft text-success" },
  low: { text: "Low", cls: "bg-warning-soft text-warning" },
  short: { text: "Short", cls: "bg-danger-soft text-danger" },
} as const;

export function LevelBadge({ level }: { level: keyof typeof LEVEL }) {
  const l = LEVEL[level];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", l.cls)}>
      <span className="dot size-1.5 bg-current" aria-hidden />
      {l.text}
    </span>
  );
}

export function ErrorText({ error }: { error: Error | null | undefined }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-danger">
      {error.message}
    </p>
  );
}

// a labelled figure in a stat strip
export function Figure({ label, value, tone }: { label: string; value: string; tone?: "warning" | "danger" | "success" }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("text-lg font-semibold tabular", tone === "warning" && "text-warning", tone === "danger" && "text-danger", tone === "success" && "text-success")}>
        {value}
      </div>
    </div>
  );
}
