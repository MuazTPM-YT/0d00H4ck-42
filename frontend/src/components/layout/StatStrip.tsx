import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type Stat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "good" | "bad" | "warn";
  // a stat that filters the list below: tap to show only those, tap again to clear
  pressed?: boolean;
  onPress?: () => void;
  disabled?: boolean;
  // a stat that opens the list behind it
  href?: string;
};

const TONE = { good: "text-success", bad: "text-danger", warn: "text-warning" };

// a row of ledger figures under the page header; cells share hairlines like a printed table
export function StatStrip({ stats, className }: { stats: Stat[]; className?: string }) {
  return (
    <div className={cn("mb-8 grid grid-cols-2 border-t border-l border-border bg-card sm:grid-cols-3 lg:grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))]", className)}>
      {stats.map((s) => {
        const body = (
          <>
            <span className={cn("label flex min-w-0 items-center gap-2", s.pressed && "text-primary-foreground/80")}>{s.label}</span>
            <span className={cn("figure min-w-0 text-[1.4rem] [overflow-wrap:anywhere] sm:text-[1.6rem]", !s.pressed && s.tone && TONE[s.tone])}>{s.value}</span>
            {s.sub && <span className={cn("text-[0.8rem] [overflow-wrap:anywhere]", s.pressed ? "text-primary-foreground/80" : "text-muted-foreground")}>{s.sub}</span>}
          </>
        );
        const cell = "grid min-w-0 content-start gap-1 border-r border-b border-border px-3 py-3 text-left [overflow-wrap:anywhere] sm:px-4";
        if (s.href)
          return (
            <Link key={s.key} href={s.href} className={cn(cell, "hover:bg-accent")}>
              {body}
            </Link>
          );
        return s.onPress ? (
          <button
            key={s.key}
            type="button"
            aria-pressed={!!s.pressed}
            disabled={s.disabled}
            onClick={s.onPress}
            className={cn(cell, "pressable disabled:opacity-45", s.pressed ? "bg-primary text-primary-foreground" : "hover:bg-accent")}
          >
            {body}
          </button>
        ) : (
          <div key={s.key} className={cell}>
            {body}
          </div>
        );
      })}
    </div>
  );
}
