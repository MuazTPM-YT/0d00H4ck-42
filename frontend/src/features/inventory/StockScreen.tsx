"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Boxes } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { kg } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { BatchSheet } from "./BatchSheet";
import type { StockRow } from "./types";
import { LevelBadge } from "./ui";
import { BatchesForItem } from "./BatchesForItem";

export type StockOverview = { items: StockRow[]; unidentified_kg: string };

export function useStock() {
  return useQuery({ queryKey: ["stock", "overview"], queryFn: () => api<StockOverview>("/inventory/stock") });
}

// R2 + R3: every yarn, usable vs held, and the projected early warning. Live via SSE.
export function StockScreen() {
  useSSE(["stock", "orders"]);
  const stock = useStock();
  const [onlyWarn, setOnlyWarn] = useState(false);
  const [item, setItem] = useState<StockRow | null>(null);
  const [batchId, setBatchId] = useState<number | null>(null);

  const rows = (stock.data?.items ?? []).filter((r) => !onlyWarn || r.level !== "ok");

  return (
    <>
      <PageHeader
        title="Yarn stock"
        description="Free = approved yarn in store minus reservations. Inspection and quarantine never count. Projected = free minus what confirmed orders still need."
        actions={
          <Button asChild variant="outline">
            <Link href="/store/receive">Receive yarn</Link>
          </Button>
        }
      />

      <label className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">
        <input type="checkbox" checked={onlyWarn} onChange={(e) => setOnlyWarn(e.target.checked)} className="size-4 accent-primary" />
        Only items that need attention
      </label>

      {stock.isError ? (
        <EmptyState icon={AlertTriangle} title="Could not load stock" action={<Button variant="outline" onClick={() => stock.refetch()}>Try again</Button>}>
          {stock.error.message}
        </EmptyState>
      ) : stock.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState icon={Boxes} title={onlyWarn ? "Nothing needs attention" : "No yarn items yet"}>
          {onlyWarn ? "Every yarn is above its reorder level." : "Add yarn items in Masters first."}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Yarn</TableHead>
                <TableHead className="text-right">On hand</TableHead>
                <TableHead className="text-right">Reserved</TableHead>
                <TableHead className="text-right">Free</TableHead>
                <TableHead className="text-right">Still needed</TableHead>
                <TableHead className="text-right">Projected</TableHead>
                <TableHead className="text-right">Reorder at</TableHead>
                <TableHead className="text-right">Inspection</TableHead>
                <TableHead className="text-right">Quarantine</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.yarn_item_id} onClick={() => setItem(r)} className="cursor-pointer">
                  <TableCell className="font-medium whitespace-nowrap">{r.label}</TableCell>
                  <TableCell className="text-right">{kg(r.on_hand_kg)}</TableCell>
                  <TableCell className="text-right">{kg(r.reserved_kg)}</TableCell>
                  <TableCell className="text-right font-medium">{kg(r.free_kg)}</TableCell>
                  <TableCell className="text-right">{kg(r.needed_by_orders_kg)}</TableCell>
                  <TableCell className="text-right font-medium">{kg(r.projected_free_kg)}</TableCell>
                  <TableCell className="text-right text-muted-foreground">{kg(r.reorder_level_kg)}</TableCell>
                  <TableCell className="text-right text-muted-foreground">{kg(r.inspection_kg)}</TableCell>
                  <TableCell className="text-right text-muted-foreground">{kg(r.quarantined_kg)}</TableCell>
                  <TableCell>
                    <LevelBadge level={r.level} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {stock.data && Number(stock.data.unidentified_kg) > 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          Plus {kg(stock.data.unidentified_kg)} waiting for identification (label missing). Not counted anywhere.
        </p>
      )}

      <BatchesForItem item={item} onClose={() => setItem(null)} onOpenBatch={setBatchId} />
      <BatchSheet batchId={batchId} onClose={() => setBatchId(null)} />
    </>
  );
}
