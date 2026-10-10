"use client";

import * as React from "react";
import { Clock } from "lucide-react";
import { Popover } from "radix-ui";
import { cn } from "@/lib/utils";
import { Select } from "./select";

// Shift times are mill-clock HH:MM, never the device timezone.
export function TimeInput({ className, value, defaultValue, onChange, ref, ...props }: React.ComponentProps<"input">) {
  const input = React.useRef<HTMLInputElement>(null);
  const [local, setLocal] = React.useState(String(value ?? defaultValue ?? ""));
  const [open, setOpen] = React.useState(false);
  const [hour, setHour] = React.useState("00");
  const [minute, setMinute] = React.useState("00");
  React.useEffect(() => { if (value !== undefined) setLocal(String(value)); }, [value]);
  function choose(next: string) {
    if (!input.current) return;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input.current, next);
    input.current.dispatchEvent(new Event("input", { bubbles: true }));
    setOpen(false);
    input.current.focus();
  }
  return <Popover.Root open={open} onOpenChange={(next) => {
    if (next) { const [h, m] = /^([01]\d|2[0-3]):[0-5]\d$/.test(local) ? local.split(":") : ["00", "00"]; setHour(h); setMinute(m); }
    setOpen(next);
  }}>
    <Popover.Anchor asChild>
      <div className={cn("relative flex h-11 min-w-0 w-full border border-input bg-card focus-within:border-ember focus-within:ring-1 focus-within:ring-ember", className)}>
        <input {...props} type="text" value={local} placeholder="HH:MM" maxLength={5} pattern="([01][0-9]|2[0-3]):[0-5][0-9]" title="Use 24-hour time, e.g. 06:00 or 22:30"
          ref={(el) => { input.current = el; if (typeof ref === "function") ref(el); else if (ref) ref.current = el; }}
          className="h-full min-w-0 w-full bg-transparent py-1 pr-12 pl-3.5 text-base outline-none"
          onChange={(event) => { setLocal(event.target.value); onChange?.(event); }} />
        <Popover.Trigger type="button" disabled={props.disabled || props.readOnly} aria-label="Choose time" className="absolute right-0 grid h-full min-h-11 w-11 place-items-center text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ember"><Clock className="size-5" /></Popover.Trigger>
      </div>
    </Popover.Anchor>
    <Popover.Portal>
      <Popover.Content align="start" sideOffset={4} collisionPadding={8} aria-label="Choose time" className="z-[80] w-64 max-w-[calc(100vw-1rem)] border border-foreground bg-popover p-3 font-sans text-popover-foreground">
        <p className="mb-3 font-semibold">Mill time · 24-hour</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="grid gap-1 text-sm">Hour<Select aria-label="Hour" value={hour} onChange={(e) => setHour(e.target.value)}>{Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0")).map((h) => <option key={h}>{h}</option>)}</Select></label>
          <label className="grid gap-1 text-sm">Minute<Select aria-label="Minute" value={minute} onChange={(e) => setMinute(e.target.value)}>{Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0")).map((m) => <option key={m}>{m}</option>)}</Select></label>
        </div>
        <div className="mt-3 flex justify-between border-t pt-2">
          <button type="button" className="min-h-11 px-3 text-ember hover:bg-accent" onClick={() => choose("")}>Clear</button>
          <button type="button" className="min-h-11 bg-primary px-4 font-semibold text-primary-foreground hover:bg-ember" onClick={() => choose(`${hour}:${minute}`)}>Set time</button>
        </div>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
