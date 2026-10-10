import { Check } from "lucide-react";

import { date, dateTime, humanize, metres } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Stage =
  | "order_received"
  | "waiting_for_yarn"
  | "in_production"
  | "being_checked"
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
  metres: { produced: string; in_qc: string; passed: string; rejected?: string; shipped: string };
  projected_finish: string | null;
  risk: "on_track" | "at_risk" | "late" | null;
  timeline: { at: string; title: string }[];
  // trucks that left; only on the buyer link
  deliveries?: { challan: string; left_at: string; rolls: number; metres: string; vehicle_no: string | null; driver: string | null }[];
};

const STEPS: { stage: Stage; label: string }[] = [
  { stage: "waiting_for_yarn", label: "Yarn" },
  { stage: "in_production", label: "Production" },
  { stage: "being_checked", label: "Quality check" },
  { stage: "ready_to_ship", label: "Ready" },
  { stage: "shipped", label: "Shipped" },
];
const ORDER: Stage[] = ["order_received", "waiting_for_yarn", "in_production", "being_checked", "ready_to_ship", "partly_shipped", "shipped"];

const HEADLINE: Record<Stage, string> = {
  order_received: "Order received, not confirmed yet",
  waiting_for_yarn: "Waiting for yarn",
  in_production: "In production",
  being_checked: "Being checked by quality",
  ready_to_ship: "Ready to ship",
  partly_shipped: "Partly shipped",
  shipped: "Shipped",
  cancelled: "Cancelled",
};

const RISK = {
  on_track: "bg-success-soft text-success",
  at_risk: "bg-warning-soft text-warning",
  late: "bg-danger-soft text-danger",
};

// answers "where is my order" and "when will it ship" in one card
export function StageCard({ t }: { t: Track }) {
  const at = ORDER.indexOf(t.stage);
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
          <div className="text-muted-foreground">{t.projected_finish ? `Expected ${date(t.projected_finish)}` : "Estimate pending"}</div>
          {t.risk && <span className={cn("mt-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", RISK[t.risk])}>{humanize(t.risk)}</span>}
        </div>
      </div>

      {t.stage !== "cancelled" && (
        <ol className="mt-6 grid grid-cols-5 gap-1" aria-label="Order progress">
          {STEPS.map((s) => {
            const idx = ORDER.indexOf(s.stage);
            const done = at > idx || t.stage === "shipped";
            const current = at === idx || (t.stage === "partly_shipped" && s.stage === "shipped");
            return (
              <li key={s.stage} className="grid gap-1 text-center text-xs">
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

      <dl className={cn("mt-6 grid grid-cols-2 gap-3 text-sm", t.metres.rejected === undefined ? "sm:grid-cols-4" : "sm:grid-cols-5")}>
        {(["produced", "in_qc", "passed", "rejected", "shipped"] as const).map((k) => {
          const value = t.metres[k];
          if (value === undefined) return null;
          return (
            <div key={k} className="rounded-md bg-muted px-3 py-2">
              <dt className="text-xs text-muted-foreground">{k === "in_qc" ? "In QC" : k === "passed" ? "Passed, on shelf" : humanize(k)}</dt>
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

// every truck that left for the buyer, with the challan number their gate will sign
export function Deliveries({ items }: { items: NonNullable<Track["deliveries"]> }) {
  if (items.length === 0) return null;
  return (
    <section className="rounded-lg border bg-card">
      <h2 className="border-b px-4 py-3 font-medium">Deliveries ({items.length})</h2>
      <ul className="divide-y text-sm">
        {items.map((d) => (
          <li key={d.challan} className="grid gap-1 px-4 py-3 sm:grid-cols-[1fr_auto]">
            <div>
              <div className="font-medium">Challan {d.challan}</div>
              <div className="text-muted-foreground">
                Left the mill {dateTime(d.left_at)}
                {d.vehicle_no && ` · vehicle ${d.vehicle_no}`}
                {d.driver && ` · driver ${d.driver}`}
              </div>
            </div>
            <div className="tabular sm:text-right">{d.rolls} {d.rolls === 1 ? "roll" : "rolls"} · {metres(d.metres)}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
