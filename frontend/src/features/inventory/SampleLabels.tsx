"use client";

import { useQuery } from "@tanstack/react-query";
import { Printer, Tags } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { kg } from "@/lib/format";
import { cn } from "@/lib/utils";

import { qrSrc, type SampleLabel } from "./types";
import { ErrorText } from "./ui";

// demo helper: real supplier labels for every open delivery, plus a wrong-colour one to show quarantine
export function SampleLabels() {
  const labels = useQuery({ queryKey: ["stock", "sample-labels"], queryFn: () => api<SampleLabel[]>("/inventory/sample-labels") });

  return (
    <>
      <div className="print:hidden">
        <PageHeader
          title="Sample supplier labels"
          description="Generated from open expected deliveries in the format agreed in docs/assumptions.md. Print, or scan straight off the screen."
          actions={
            <>
              <Button asChild variant="outline"><Link href="/store/receive">Back to receiving</Link></Button>
              <Button onClick={() => window.print()} disabled={!labels.data?.length}><Printer /> Print</Button>
            </>
          }
        />
      </div>
      <ErrorText error={labels.error} />
      {labels.isPending && <Skeleton className="h-64 w-full" />}
      {labels.data?.length === 0 && (
        <EmptyState icon={Tags} title="No open deliveries">
          Add an expected delivery on the receive screen, then come back.
        </EmptyState>
      )}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 print:grid-cols-2">
        {labels.data?.map((l) => (
          <li key={l.payload} className={cn("flex break-inside-avoid flex-col items-center gap-2 rounded-lg border bg-card p-4 text-center", l.kind === "wrong_colour" && "border-danger")}>
            <img src={qrSrc(l.payload)} alt={`QR label: ${l.title}`} className="size-44 rounded bg-white p-1" />
            <div className={cn("text-sm font-semibold", l.kind === "wrong_colour" && "text-danger")}>{l.title}</div>
            <div className="text-xs text-muted-foreground">
              {l.supplier} · {kg(l.kg)}
            </div>
            <code className="w-full rounded bg-muted p-2 text-left text-xs break-all">{l.payload}</code>
          </li>
        ))}
      </ul>
    </>
  );
}
