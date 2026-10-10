"use client";

import { Lightbulb, RefreshCw } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { dateTime, humanize } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { type Insight, type InsightFilters, KIND_LABEL, useInsights, useRunDetectors } from "./api";
import { BriefingCard } from "./AttentionList";
import { InsightSheet } from "./InsightSheet";

const LIMIT = 25;
const selectClass = "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs sm:w-44";

const COLUMNS: Column<Insight>[] = [
  { key: "severity", header: "Severity", cell: (i) => <StatusBadge status={i.severity} /> },
  {
    key: "title",
    header: "Finding",
    cell: (i) => (
      <div className="grid min-w-56 gap-0.5">
        <span className="font-medium whitespace-normal">{i.title}</span>
        <span className="text-xs text-muted-foreground">{KIND_LABEL[i.kind] ?? humanize(i.kind)}</span>
      </div>
    ),
  },
  { key: "status", header: "Status", cell: (i) => <StatusBadge status={i.status} /> },
  { key: "found", header: "Found", cell: (i) => <span className="tabular">{dateTime(i.created_at)}</span> },
];

function Filter({ id, label, value, options, onChange }: { id: string; label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={selectClass}>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </div>
  );
}

// findings by severity; the open one lives in the URL (?id=12) so a link can point at it
export function InsightsPage() {
  useSSE(["insights"]);
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const openId = params.get("id") ? Number(params.get("id")) : null;
  const [filters, setFilters] = useState<InsightFilters>({ status: "open", severity: "", kind: "" });
  const [offset, setOffset] = useState(0);
  const insights = useInsights(filters, offset, LIMIT);
  const run = useRunDetectors();

  const setFilter = (key: keyof InsightFilters) => (value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setOffset(0);
  };
  const open = (id: number | null) => router.replace(id ? `${pathname}?id=${id}` : pathname, { scroll: false });

  return (
    <>
      <PageHeader
        title="Insights"
        description="Found by statistics on the mill's own records. The text only explains numbers that are in the record."
        actions={
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            <RefreshCw className={run.isPending ? "animate-spin" : undefined} /> Run detectors now
          </Button>
        }
      />
      {run.isError && (
        <p role="alert" className="mb-4 text-sm text-danger">
          {run.error.message}
        </p>
      )}
      {run.isSuccess && (
        <p role="status" className="mb-4 text-sm text-muted-foreground">
          Done: {run.data.created} new, {run.data.updated} updated, {run.data.unchanged} unchanged.
        </p>
      )}
      <BriefingCard />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <Filter id="status" label="Status" value={filters.status} onChange={setFilter("status")} options={[["open", "Open"], ["acknowledged", "Acknowledged"], ["resolved", "Resolved"], ["", "Any status"]]} />
        <Filter id="severity" label="Severity" value={filters.severity} onChange={setFilter("severity")} options={[["", "Any severity"], ["critical", "Critical"], ["warn", "Warning"], ["info", "Info"]]} />
        <Filter id="kind" label="Kind" value={filters.kind} onChange={setFilter("kind")} options={[["", "Any kind"], ...Object.entries(KIND_LABEL)]} />
      </div>
      <DataTable
        columns={COLUMNS}
        query={insights}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={(i) => open(i.id)}
        empty={
          <EmptyState icon={Lightbulb} title="No findings here">
            Detectors run every 5 minutes. Change the filters, or run them now.
          </EmptyState>
        }
      />
      <InsightSheet id={openId} onClose={() => open(null)} />
    </>
  );
}
