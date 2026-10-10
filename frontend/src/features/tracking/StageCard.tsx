import { Check } from "lucide-react";

import { date, dateTime, humanize, metres } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Stage =
  | "order_received"
  | "waiting_for_yarn"
  | "planned"
  | "in_production"
  | "being_checked"
  | "short"
  | "ready_to_ship"
  | "partly_shipped"
  | "shipped"
  | "cancelled";

// same shape as TrackOut in backend/app/modules/tracking/schemas.py
export type Track = {
  order_code: string;
  fabric: string;
  colour: string;
  qty_m: string;
  deadline: string;
  stage: Stage;
  production_stage: string | null;
  progress_pct: number | null;
  // rejected comes only on the staff view; buyer link never gets it
  metres: { produced: string; in_production: string; in_qc: string; passed: string; rejected?: string; shipped: string };
  projected_finish: string | null;
  risk: "on_track" | "at_risk" | "late" | null;
  timeline: { at: string; title: string }[];
};

// same 2% as the server: rolls never cut to the exact metre
const DONE_SHARE = 0.98;
type Step = "yarn" | "production" | "qc" | "ready" | "shipped";
const STEPS: { key: Step; label: string }[] = [
  { key: "yarn", label: "Yarn" },
  { key: "production", label: "Production" },
  { key: "qc", label: "Quality check" },
  { key: "ready", label: "Ready" },
  { key: "shipped", label: "Shipped" },
];
const STARTED: Stage[] = ["in_production", "being_checked", "short", "ready_to_ship", "partly_shipped", "shipped"];

// each step marked by its own metres, not by where the headline stage sits
function stepState(t: Track, step: Step): "done" | "current" | "todo" {
  const m = t.metres;
  const enough = Number(t.qty_m) * DONE_SHARE;
  const good = Number(m.passed) + Number(m.shipped);
  const onFloor = Number(m.in_production) > 0;
  const inQc = Number(m.in_qc) > 0;
  if (t.stage === "shipped") return "done";
  switch (step) {
    case "yarn":
      return STARTED.includes(t.stage) ? "done" : t.stage === "waiting_for_yarn" || t.stage === "planned" ? "current" : "todo";
    case "production":
      if (t.stage === "in_production" || t.stage === "short" || onFloor) return "current";
      return STARTED.includes(t.stage) ? "done" : "todo";
    case "qc":
      if (inQc || t.stage === "being_checked") return "current";
      return good >= enough ? "done" : "todo";
    case "ready":
      if (good >= enough && Number(m.shipped) < enough) return t.stage === "ready_to_ship" ? "current" : "done";
      return "todo";
    case "shipped":
      return t.stage === "partly_shipped" ? "current" : "todo";
  }
}

const HEADLINE: Record<Stage, string> = {
  order_received: "Order received, not confirmed yet",
  waiting_for_yarn: "Waiting for yarn",
  planned: "Ready to start",
  in_production: "In production",
  being_checked: "Being checked by quality",
  short: "Being completed",
  ready_to_ship: "Ready to ship",
  partly_shipped: "Partly shipped",
  shipped: "Shipped",
  cancelled: "Cancelled",
};

const METRE_LABEL: Record<string, string> = {
  in_production: "Woven, in process",
  in_qc: "In QC",
  passed: "Passed, on shelf",
};

const RISK = {
  on_track: "bg-success-soft text-success",
  at_risk: "bg-warning-soft text-warning",
  late: "bg-danger-soft text-danger",
};

// answers "where is my order" and "when will it ship" in one card
export function StageCard({ t }: { t: Track }) {
  const headline =
    t.stage === "in_production" && t.production_stage
      ? `In production: ${humanize(t.production_stage)} ${t.progress_pct ?? 0}%`
      : HEADLINE[t.stage];

  return (
    <section className="rounded-lg border bg-card p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm text-muted-foreground">{t.order_code} · {t.fabric}, {t.colour} · {metres(t.qty_m)}</div>
          <h2 className="mt-1 text-2xl font-semibold">{headline}</h2>
        </div>
        <div className="text-right text-sm">
          <div>Due {date(t.deadline)}</div>
          {t.stage !== "shipped" && t.stage !== "cancelled" && (
            <div className="text-muted-foreground">{t.projected_finish ? `Expected ${date(t.projected_finish)}` : "Estimate pending"}</div>
          )}
          {t.risk && <span className={cn("mt-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", RISK[t.risk])}>{humanize(t.risk)}</span>}
        </div>
      </div>

      {t.stage !== "cancelled" && (
        <ol className="mt-6 grid grid-cols-5 gap-1" aria-label="Order progress">
          {STEPS.map((s) => {
            const state = stepState(t, s.key);
            const done = state === "done";
            const current = state === "current";
            return (
              <li key={s.key} className="grid gap-1 text-center text-xs">
                <span className={cn("h-2 rounded-full", done ? "bg-success" : current ? "bg-primary" : "bg-muted")} />
                <span className={cn("flex items-center justify-center gap-1", current ? "font-semibold text-foreground" : "text-muted-foreground")}>
                  {done && <Check className="size-3" aria-hidden />}
                  {s.label}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      <dl className={cn("mt-6 grid grid-cols-2 gap-3 text-sm", t.metres.rejected === undefined ? "sm:grid-cols-5" : "sm:grid-cols-6")}>
        {(["produced", "in_production", "in_qc", "passed", "rejected", "shipped"] as const).map((k) => {
          const value = t.metres[k];
          if (value === undefined) return null;
          return (
            <div key={k} className="rounded-md bg-muted px-3 py-2">
              <dt className="text-xs text-muted-foreground">{METRE_LABEL[k] ?? humanize(k)}</dt>
              <dd className="font-semibold tabular">{metres(value)}</dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

export function Timeline({ events }: { events: Track["timeline"] }) {
  if (events.length === 0) return null;
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="mb-3 font-medium">Timeline</h2>
      <ol className="grid gap-3 border-l pl-4">
        {events.map((e, i) => (
          <li key={i} className="relative text-sm">
            <span className="dot absolute top-1.5 -left-[1.3rem] size-2 bg-primary" aria-hidden />
            <div>{e.title}</div>
            <div className="text-xs text-muted-foreground">{dateTime(e.at)}</div>
          </li>
        ))}
      </ol>
    </section>
  );
}
