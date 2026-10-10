"use client";

import * as React from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Popover } from "radix-ui";
import { cn } from "@/lib/utils";
import { millDate, validDate } from "@/lib/validation";
import { Select } from "./select";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const iso = (date: Date) => date.toISOString().slice(0, 10);
const dayDate = (day: string) => new Date(`${day}T12:00:00Z`);
const monthStart = (day: string) => `${day.slice(0, 7)}-01`;

// One ISO form value, with a themed calendar and editable text as a keyboard fallback.
export function DateInput({ className, value, defaultValue, onChange, onBlur, ref, min, max, type, ...props }: React.ComponentProps<"input">) {
  const input = React.useRef<HTMLInputElement>(null);
  const calendar = React.useRef<HTMLDivElement>(null);
  const [local, setLocal] = React.useState(String(value ?? defaultValue ?? ""));
  const selected = local;
  React.useEffect(() => { if (value !== undefined) setLocal(String(value)); }, [value]);
  const isMonth = type === "month";
  const selectedDay = isMonth && selected ? `${selected}-01` : selected;
  const lowerValue = min ? `${min}${isMonth ? "-01" : ""}` : "";
  const upperValue = max ? `${max}${isMonth ? "-01" : ""}` : "";
  const lower = validDate(lowerValue) ? lowerValue : undefined;
  const upper = validDate(upperValue) ? (isMonth ? iso(new Date(Date.UTC(Number(upperValue.slice(0, 4)), Number(upperValue.slice(5, 7)), 0))) : upperValue) : undefined;
  const today = millDate();
  const initial = validDate(selectedDay, lower, upper) ? selectedDay : (lower && today < lower ? lower : upper && today > upper ? upper : today);
  const [month, setMonth] = React.useState(monthStart(initial));
  const [focused, setFocused] = React.useState(initial);
  const [open, setOpen] = React.useState(false);
  const monthDate = dayDate(month);
  const year = monthDate.getUTCFullYear();
  const monthIndex = monthDate.getUTCMonth();
  const firstWeekday = (monthDate.getUTCDay() + 6) % 7;
  const lastDate = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const firstYear = lower ? Number(lower.slice(0, 4)) : Math.min(year, Number(today.slice(0, 4)) - 100);
  const lastYear = upper ? Number(upper.slice(0, 4)) : Math.max(year, Number(today.slice(0, 4)) + 20);

  function validate(el: HTMLInputElement) {
    const day = isMonth && el.value ? `${el.value}-01` : el.value;
    let message = "";
    if (day && !validDate(day)) message = isMonth ? "Enter a valid month as YYYY-MM" : "Enter a valid date as YYYY-MM-DD";
    else if (day && lower && day < lower) message = `Date must be on or after ${min}`;
    else if (day && upper && day > upper) message = `Date must be on or before ${max}`;
    el.setCustomValidity(message);
  }

  React.useEffect(() => { if (input.current) validate(input.current); }, [selected, lower, upper]);
  React.useEffect(() => {
    const form = input.current?.form;
    const reset = () => { setLocal(String(defaultValue ?? "")); setOpen(false); };
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [defaultValue]);

  function choose(day: string) {
    if (day && !validDate(day, lower, upper)) return;
    const el = input.current;
    if (!el) return;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, isMonth ? day.slice(0, 7) : day);
    validate(el);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    setOpen(false);
    el.focus();
  }

  function moveMonth(by: number) {
    const next = iso(new Date(Date.UTC(year, monthIndex + by, 1)));
    setMonth(next);
    setFocused(lower && next < lower ? lower : next);
  }

  function keyDay(event: React.KeyboardEvent, day: string) {
    const date = dayDate(day);
    const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key];
    if (offset !== undefined) date.setUTCDate(date.getUTCDate() + offset);
    else if (event.key === "Home") date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
    else if (event.key === "End") date.setUTCDate(date.getUTCDate() + 6 - (date.getUTCDay() + 6) % 7);
    else if (event.key === "PageUp" || event.key === "PageDown") {
      const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + (event.key === "PageUp" ? -1 : 1), 1));
      const last = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
      date.setTime(target.getTime());
      date.setUTCDate(Math.min(Number(day.slice(-2)), last));
    } else return;
    event.preventDefault();
    let next = iso(date);
    if (lower && next < lower) next = lower;
    if (upper && next > upper) next = upper;
    setFocused(next);
    setMonth(monthStart(next));
    requestAnimationFrame(() => calendar.current?.querySelector<HTMLButtonElement>(`[data-day="${next}"]`)?.focus());
  }

  return (
    <Popover.Root open={open} onOpenChange={(next) => {
      if (next) { setMonth(monthStart(initial)); setFocused(initial); }
      setOpen(next);
    }}>
      <Popover.Anchor asChild>
        <div className={cn("relative flex h-11 min-w-0 w-full items-center border border-input bg-card text-base focus-within:border-ember focus-within:ring-1 focus-within:ring-ember has-[input[aria-invalid=true]]:border-destructive", className)}>
          <input {...props} type="text" inputMode="text" value={selected} placeholder={isMonth ? "YYYY-MM" : "YYYY-MM-DD"} maxLength={isMonth ? 7 : 10}
            aria-invalid={props["aria-invalid"] || (!!selected && !validDate(selectedDay, lower, upper))}
            ref={(el) => { input.current = el; if (typeof ref === "function") ref(el); else if (ref) ref.current = el; }}
            className="h-full min-w-0 w-full bg-transparent py-1 pr-12 pl-3.5 outline-none disabled:opacity-50 aria-invalid:text-destructive"
            onChange={(event) => { setLocal(event.target.value); validate(event.target); onChange?.(event); }}
            onBlur={(event) => { validate(event.target); onBlur?.(event); }}
          />
          <Popover.Trigger type="button" disabled={props.disabled || props.readOnly} aria-label={`Choose date${props["aria-label"] ? `: ${props["aria-label"]}` : ""}`}
            className="absolute right-0 grid h-full min-h-11 w-11 place-items-center text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ember disabled:opacity-40">
            <CalendarDays className="size-5" />
          </Popover.Trigger>
        </div>
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content ref={calendar} aria-label="Choose a date" align="start" sideOffset={4} collisionPadding={8}
          onOpenAutoFocus={(event) => { event.preventDefault(); requestAnimationFrame(() => calendar.current?.querySelector<HTMLButtonElement>(`[data-day="${isMonth ? monthStart(initial) : initial}"]`)?.focus()); }}
          onCloseAutoFocus={(event) => { event.preventDefault(); input.current?.focus(); }}
          className="z-[80] max-h-[var(--radix-popover-content-available-height)] w-[min(23rem,calc(100vw-1rem))] overflow-y-auto border border-foreground bg-popover p-2 font-sans text-base text-popover-foreground outline-none sm:p-3">
          <div className="mb-2 flex items-center gap-1">
            {!isMonth && <Select aria-label="Calendar month" value={monthIndex} onChange={(e) => { const next = `${year}-${String(Number(e.target.value) + 1).padStart(2, "0")}-01`; setMonth(next); setFocused(lower && next < lower ? lower : next); }} className="flex-1 px-2">
              {MONTHS.map((name, i) => <option key={name} value={i} disabled={!!lower && year === Number(lower.slice(0, 4)) && i < Number(lower.slice(5, 7)) - 1 || !!upper && year === Number(upper.slice(0, 4)) && i > Number(upper.slice(5, 7)) - 1}>{name}</option>)}
            </Select>}
            <Select aria-label="Calendar year" value={year} onChange={(e) => { const nextYear = Number(e.target.value); let next = `${nextYear}-${String(monthIndex + 1).padStart(2, "0")}-01`; if (lower && next < monthStart(lower)) next = monthStart(lower); if (upper && next > monthStart(upper)) next = monthStart(upper); setMonth(next); setFocused(lower && next < lower ? lower : next); }} className="w-24 shrink-0 px-2">
              {Array.from({ length: lastYear - firstYear + 1 }, (_, i) => firstYear + i).map((y) => <option key={y} value={y}>{y}</option>)}
            </Select>
          </div>
          <div className="sr-only" aria-live="polite">{MONTHS[monthIndex]} {year}</div>
          {isMonth ? <div className="grid grid-cols-3 gap-1" aria-label={`Months in ${year}`}>
            {MONTHS.map((name, i) => {
              const day = `${year}-${String(i + 1).padStart(2, "0")}-01`;
              return <button type="button" key={name} data-day={day} disabled={!validDate(day, lower, upper)} onClick={() => choose(day)}
                className={cn("min-h-12 px-2 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ember disabled:opacity-30", selectedDay === day && "bg-primary text-primary-foreground")}>{name}</button>;
            })}
          </div> : <div className="grid grid-cols-7 text-center" role="grid" aria-label={`${MONTHS[monthIndex]} ${year}`}>
            <div role="row" className="contents">{["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((day) => <span key={day} role="columnheader" className="py-2 text-sm text-muted-foreground">{day}</span>)}</div>
            {Array.from({ length: Math.ceil((firstWeekday + lastDate) / 7) }, (_, week) => (
              <div role="row" className="contents" key={week}>
                {Array.from({ length: 7 }, (_, col) => {
                  const number = week * 7 + col - firstWeekday + 1;
                  if (number < 1 || number > lastDate) return <div role="gridcell" key={col} />;
                  const day = `${month.slice(0, 7)}-${String(number).padStart(2, "0")}`;
                  return <div role="gridcell" aria-selected={day === selected} key={col}>
                    <button type="button" data-day={day} aria-label={dayDate(day).toLocaleDateString("en-IN", { dateStyle: "full", timeZone: "UTC" })} aria-current={day === today ? "date" : undefined}
                      disabled={!validDate(day, lower, upper)} tabIndex={day === focused ? 0 : -1} onKeyDown={(e) => keyDay(e, day)} onClick={() => choose(day)}
                      className={cn("h-11 w-full border border-transparent outline-none hover:border-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ember disabled:opacity-30 disabled:hover:border-transparent", day === selected ? "bg-primary font-semibold text-primary-foreground" : day === today ? "border-ember text-ember" : "hover:bg-accent")}>{number}</button>
                  </div>;
                })}
              </div>
            ))}
          </div>}
          <div className="mt-2 flex justify-between border-t pt-2">
            <button type="button" aria-label={isMonth ? "Previous year" : "Previous month"} disabled={!!lower && (isMonth ? year <= Number(lower.slice(0, 4)) : month.slice(0, 7) <= lower.slice(0, 7))} onClick={() => moveMonth(isMonth ? -12 : -1)} className="grid size-11 shrink-0 place-items-center hover:bg-accent focus-visible:outline-ember disabled:opacity-30"><ChevronLeft className="size-5" /></button>
            <button type="button" className="min-h-11 px-3 text-ember hover:bg-accent focus-visible:outline-ember" onClick={() => choose("")}>Clear</button>
            <button type="button" className="min-h-11 px-3 font-semibold text-ember hover:bg-accent focus-visible:outline-ember disabled:opacity-30" disabled={!validDate(today, lower, upper)} onClick={() => choose(today)}>{isMonth ? "This month" : "Today"}</button>
            <button type="button" aria-label={isMonth ? "Next year" : "Next month"} disabled={!!upper && (isMonth ? year >= Number(upper.slice(0, 4)) : month.slice(0, 7) >= upper.slice(0, 7))} onClick={() => moveMonth(isMonth ? 12 : 1)} className="grid size-11 shrink-0 place-items-center hover:bg-accent focus-visible:outline-ember disabled:opacity-30"><ChevronRight className="size-5" /></button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
