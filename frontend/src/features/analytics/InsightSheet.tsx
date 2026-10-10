"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { dateTime, humanize } from "@/lib/format";

import { type Insight, KIND_LABEL, type RecordRef, recordHref, useInsight, useInsightAction } from "./api";

const HIDDEN = new Set(["key", "records", "check"]);
const SHOWN_RECORDS = 40;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-2 border-t pt-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Value({ value }: { value: unknown }): ReactNode {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value) && value.every((v) => typeof v !== "object")) return value.join(", ");
  if (Array.isArray(value)) return <RowsTable rows={value as Record<string, unknown>[]} />;
  if (typeof value === "object")
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${humanize(k)}: ${String(v)}`)
      .join(" · ");
  return String(value);
}

// lists inside the facts (causes, daily figures) as a small table
function RowsTable({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = Object.keys(rows[0] ?? {});
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            {cols.map((c) => (
              <th key={c} className="py-1 pr-3 font-medium">{humanize(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((r, i) => (
            <tr key={i} className="border-t">
              {cols.map((c) => (
                <td key={c} className="py-1 pr-3">{String(r[c] ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// every number shown in the text comes from this table, and every row of it from a record
function FactsTable({ facts }: { facts: Insight["facts"] }) {
  const rows = Object.entries(facts).filter(([k]) => !HIDDEN.has(k));
  return (
    <dl className="grid gap-y-2 text-sm sm:grid-cols-[minmax(8rem,auto)_1fr] sm:gap-x-4">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{humanize(k)}</dt>
          <dd className="tabular min-w-0 break-words">
            <Value value={v} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Records({ records }: { records: RecordRef[] }) {
  const [all, setAll] = useState(false);
  if (records.length === 0) return <p className="text-sm text-muted-foreground">No linked records.</p>;
  const shown = all ? records : records.slice(0, SHOWN_RECORDS);
  return (
    <>
      <ul className="flex flex-wrap gap-2">
        {shown.map((r) => {
          const href = recordHref(r);
          const text = `${humanize(r.type).replace(/s$/, "")} ${r.code}`;
          return (
            <li key={`${r.type}-${r.id}`}>
              {href ? (
                <Link href={href} className="inline-flex rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent">
                  {text}
                </Link>
              ) : (
                <span className="inline-flex rounded-md border px-2 py-1 text-xs text-muted-foreground">{text}</span>
              )}
            </li>
          );
        })}
      </ul>
      {records.length > SHOWN_RECORDS && !all && (
        <Button variant="link" size="sm" className="justify-self-start px-0" onClick={() => setAll(true)}>
          Show all {records.length}
        </Button>
      )}
    </>
  );
}

// acknowledge = "I am on it", resolve = "fixed"; both need a note, both land in the audit log
function Actions({ insight }: { insight: Insight }) {
  const action = useInsightAction(insight.id);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string>();
  if (insight.status === "resolved") return <p className="text-sm text-muted-foreground">Resolved. The detector will stay quiet about this finding.</p>;

  const submit = (kind: "acknowledge" | "resolve") => (e: { preventDefault: () => void }) => {
    e.preventDefault();
    if (!note.trim()) return setError("Write what you did or will do");
    setError(undefined);
    action.mutate({ action: kind, note: note.trim() }, { onSuccess: () => setNote(""), onError: (err) => setError(err.message) });
  };

  return (
    <form className="grid gap-3" onSubmit={submit("resolve")} noValidate>
      <FormField name="note" label="Note" error={error} required hint="Who is on it, or what was fixed">
        <textarea
          id="note"
          name="note"
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          aria-invalid={!!error}
          aria-describedby={error ? "note-error" : undefined}
          className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive md:text-sm"
        />
      </FormField>
      <div className="flex flex-wrap gap-2">
        {insight.status === "open" && (
          <Button type="button" variant="outline" className="h-11 sm:h-9" disabled={action.isPending} onClick={submit("acknowledge")}>
            Acknowledge
          </Button>
        )}
        <Button type="submit" className="h-11 sm:h-9" disabled={action.isPending}>
          Resolve
        </Button>
      </div>
    </form>
  );
}

// one finding: plain-language text, the numbers behind it, the records behind the numbers
export function InsightSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const insight = useInsight(id);
  const data = insight.data;

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <div className="grid gap-4 px-4 pb-6">
          {insight.isError ? (
            <EmptyState icon={AlertTriangle} title="Could not load this finding" className="mt-12" action={<Button variant="outline" onClick={() => insight.refetch()}>Try again</Button>}>
              {insight.error.message}
            </EmptyState>
          ) : !data ? (
            <>
              <SheetTitle className="sr-only">Loading finding</SheetTitle>
              <Skeleton className="mt-12 h-8 w-3/4" />
              <Skeleton className="h-24 w-full" />
            </>
          ) : (
            <>
              <SheetHeader className="px-0">
                <SheetTitle className="pr-6">{data.title}</SheetTitle>
                <SheetDescription className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={data.severity} />
                  <StatusBadge status={data.status} />
                  <span>
                    {KIND_LABEL[data.kind] ?? humanize(data.kind)} · found {dateTime(data.created_at)}
                  </span>
                </SheetDescription>
              </SheetHeader>
              <Section title="What we found">
                <p className="text-sm leading-relaxed">{data.narrative ?? "—"}</p>
              </Section>
              <Section title="The numbers">
                <FactsTable facts={data.facts} />
              </Section>
              <Section title="Records behind it">
                <Records records={data.facts.records ?? []} />
              </Section>
              <Section title="Action">
                <Actions insight={data} />
              </Section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
