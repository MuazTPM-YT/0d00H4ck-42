"use client";

import { AlertTriangle, CheckCircle2, ChevronRight, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { type AttentionItem, useAttention, useBriefing } from "./api";
import { InsightSheet } from "./InsightSheet";

const EDGE: Record<AttentionItem["severity"], string> = {
  critical: "border-l-danger",
  warn: "border-l-warning",
  info: "border-l-info",
};

// two or three sentences for the top of a role home
export function BriefingCard() {
  const briefing = useBriefing();
  return (
    <section aria-label="Briefing" className="mb-6 flex gap-3 rounded-lg border bg-card p-4">
      <Sparkles className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
      {briefing.isPending ? (
        <Skeleton className="h-5 w-full max-w-xl" />
      ) : briefing.isError ? (
        <p className="text-sm text-muted-foreground">Briefing unavailable: {briefing.error.message}</p>
      ) : (
        <p className="text-sm leading-relaxed">{briefing.data.text}</p>
      )}
    </section>
  );
}

// a role's to-do list; every item opens its record. Drop-in for any role home.
export function AttentionList({ title = "Needs attention" }: { title?: string }) {
  const attention = useAttention();
  // findings open in place: not every role can open the /insights page
  const [insightId, setInsightId] = useState<number | null>(null);

  return (
    <section aria-labelledby="attention-title" className="grid gap-3">
      <h2 id="attention-title" className="text-base font-semibold">
        {title}
      </h2>
      {attention.isError ? (
        <EmptyState icon={AlertTriangle} title="Could not load the list" action={<Button variant="outline" onClick={() => attention.refetch()}>Try again</Button>}>
          {attention.error.message}
        </EmptyState>
      ) : attention.isPending ? (
        Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)
      ) : attention.data.length === 0 ? (
        <EmptyState icon={CheckCircle2} title="All clear">
          Nothing needs you right now.
        </EmptyState>
      ) : (
        <ul className="grid gap-2">
          {attention.data.map((item) => {
            const body = (
              <>
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate font-medium">{item.title}</span>
                  {item.detail && <span className="line-clamp-2 text-sm text-muted-foreground">{item.detail}</span>}
                </span>
                <StatusBadge status={item.severity} className="hidden sm:inline-flex" />
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              </>
            );
            const row = cn(
              "flex min-h-14 w-full items-center gap-3 rounded-lg border border-l-4 bg-card px-4 py-3 text-left hover:bg-accent",
              EDGE[item.severity],
            );
            return (
              <li key={`${item.kind}-${item.entity_type}-${item.entity_id}`}>
                {item.kind === "insight" ? (
                  <button type="button" className={row} onClick={() => setInsightId(item.entity_id)}>
                    {body}
                  </button>
                ) : (
                  <Link href={item.href} className={row}>
                    {body}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <InsightSheet id={insightId} onClose={() => setInsightId(null)} />
    </section>
  );
}
