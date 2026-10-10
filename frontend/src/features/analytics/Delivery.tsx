"use client";

import { AlertTriangle, CalendarCheck, ChevronDown } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import { date, dateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { type DeliveryEstimate, type Risk, useDeliveryBoard, useDeliveryEstimate } from "./api";

const RISK_STYLE: Record<Risk, string> = {
  on_track: "bg-success-soft text-success",
  at_risk: "bg-warning-soft text-warning",
  late: "bg-danger-soft text-danger",
};

// StatusBadge has no forecast states, so the same pill shape with the same tokens
export function RiskBadge({ risk }: { risk: Risk }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", RISK_STYLE[risk])}>
      <span className="dot size-1.5 bg-current" aria-hidden />
      {humanize(risk)}
    </span>
  );
}

const slack = (hours: number | null) =>
  hours === null ? "—" : `${hours < 0 ? "−" : "+"}${Math.abs(hours) >= 48 ? `${Math.round(Math.abs(hours) / 24)} d` : `${Math.round(Math.abs(hours))} h`}`;

// the "how was this calculated" part: per stage machine, remaining work, speed used, window
export function ForecastBasis({ estimate }: { estimate: DeliveryEstimate }) {
  const { basis } = estimate;
  return (
    <div className="grid gap-3 text-sm">
      {estimate.blocked_by.length > 0 && (
        <p className="text-danger">No working machine for {estimate.blocked_by.join(", ")}: no date until one is free.</p>
      )}
      {estimate.stages.length === 0 ? (
        <p className="text-muted-foreground">All production done. Only QC and dispatch left.</p>
      ) : (
        <ul className="grid gap-1">
          {estimate.stages.map((s) => (
            <li key={s.work_order_id} className="tabular">
              <span className="font-medium">{s.code}</span> {s.stage}: {s.remaining} {s.unit} left
              {s.machine && (
                <>
                  {" "}on {s.machine} at {basis.throughputs[s.machine]?.per_hour} {s.unit}/h ({basis.throughputs[s.machine]?.from}), {dateTime(s.start)} → {dateTime(s.end)}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground">
        Plus {basis.qc_hours} h for QC and {basis.dispatch_hours} h for dispatch. A stopped machine counts back after {basis.repair_hours} h (median repair). Rule: {basis.rule}.
      </p>
    </div>
  );
}

// every confirmed order with its forecast, worst first; refreshes when the floor changes
export function DeliveryBoard() {
  const board = useDeliveryBoard();
  const [open, setOpen] = useState<number | null>(null);

  if (board.isError)
    return (
      <EmptyState icon={AlertTriangle} title="Could not load forecasts" action={<Button variant="outline" onClick={() => board.refetch()}>Try again</Button>}>
        {board.error.message}
      </EmptyState>
    );
  if (board.data?.length === 0)
    return (
      <EmptyState icon={CalendarCheck} title="No confirmed orders">
        Forecasts appear when the accounts desk confirms an order.
      </EmptyState>
    );

  return (
    <div className="min-w-0 border border-border bg-card">
      <Table containerClassName="scroll-panel max-h-[34rem]">
        <TableHeader className="sticky top-0 z-10 bg-card">
          <TableRow>
            <TableHead>Order</TableHead>
            <TableHead>Deadline</TableHead>
            <TableHead>Forecast</TableHead>
            <TableHead className="text-right">Slack</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-10"><span className="sr-only">Details</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {board.isPending
            ? Array.from({ length: 4 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                </TableRow>
              ))
            : board.data.map((e) => (
                <Fragment key={e.order_id}>
                  <TableRow>
                    <TableCell>
                      <Link href={`/orders/${e.order_id}`} className="font-medium hover:underline">
                        {e.order_code}
                      </Link>
                    </TableCell>
                    <TableCell className="tabular">{date(e.deadline)}</TableCell>
                    <TableCell className="tabular">{dateTime(e.expected_at)}</TableCell>
                    <TableCell className="tabular text-right">{slack(e.slack_hours)}</TableCell>
                    <TableCell>
                      <RiskBadge risk={e.status} />
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`How ${e.order_code} was forecast`}
                        aria-expanded={open === e.order_id}
                        onClick={() => setOpen(open === e.order_id ? null : e.order_id)}
                      >
                        <ChevronDown className={cn("transition-transform", open === e.order_id && "rotate-180")} />
                      </Button>
                    </TableCell>
                  </TableRow>
                  {open === e.order_id && (
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableCell colSpan={6} className="whitespace-normal">
                        <ForecastBasis estimate={e} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
        </TableBody>
      </Table>
    </div>
  );
}

// drop-in for the order page (/orders/[id]): forecast date, status and how it was worked out
export function DeliveryEstimateCard({ orderId }: { orderId: number }) {
  const estimate = useDeliveryEstimate(orderId);
  if (estimate.error instanceof ApiError && estimate.error.code === "not_forecastable") return null;
  return (
    <section aria-label="Delivery forecast" className="grid gap-3 rounded-lg border bg-card p-4">
      {estimate.isPending ? (
        <Skeleton className="h-6 w-64" />
      ) : estimate.isError ? (
        <p className="text-sm text-muted-foreground">Forecast unavailable: {estimate.error.message}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-base font-semibold">Forecast delivery {dateTime(estimate.data.expected_at)}</h2>
            <RiskBadge risk={estimate.data.status} />
            <span className="text-sm text-muted-foreground">due {date(estimate.data.deadline)}</span>
          </div>
          <ForecastBasis estimate={estimate.data} />
        </>
      )}
    </section>
  );
}
