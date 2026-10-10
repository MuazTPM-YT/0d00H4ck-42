"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, PackageCheck, Truck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";
import { cn } from "@/lib/utils";

import { CreateDispatchForm } from "./DispatchList";
import type { CornerItem, ShelfGroup } from "./types";

// finished fabric on the shelf, grouped by order, plus rolls forgotten in a corner (R16, R22)
export function FinishedStock() {
  useSSE(["dispatch", "quality"]);
  const router = useRouter();
  const role = useMe().data?.role;
  const [shipOrder, setShipOrder] = useState<number | null>(null);
  const shelf = useQuery({ queryKey: ["dispatch", "shelf"], queryFn: () => api<ShelfGroup[]>("/dispatch/finished-stock") });
  const corner = useQuery({ queryKey: ["dispatch", "corner"], queryFn: () => api<CornerItem[]>("/dispatch/corner-check") });
  const canLoad = role === "dispatch" || role === "owner";
  const total = (shelf.data ?? []).reduce((sum, g) => sum + Number(g.on_shelf_m), 0);

  return (
    <>
      <PageHeader
        title="Finished stock"
        description={shelf.data ? `${shelf.data.reduce((n, g) => n + g.rolls.length, 0)} rolls, ${metres(total)} passed and waiting to ship.` : "Passed rolls waiting to ship."}
      />
      {corner.data && corner.data.length > 0 && (
        <section className="mb-6 border border-warning bg-warning-soft p-4">
          <h2 className="mb-2 flex items-center gap-2 text-base text-warning"><AlertTriangle className="size-5" /> Needs a look ({corner.data.length})</h2>
          <ul className="scroll-panel grid max-h-44 gap-1 text-sm">
            {corner.data.map((c) => (
              <li key={c.roll_id}><span className="font-medium">{c.roll_code}</span> ({c.order_code}, {metres(c.length_m)}, {c.days_on_shelf} days): {c.reasons.join("; ")}</li>
            ))}
          </ul>
        </section>
      )}
      {shelf.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : shelf.isError ? (
        <EmptyState icon={AlertTriangle} title="Could not load the shelf" action={<Button variant="outline" onClick={() => shelf.refetch()}>Try again</Button>}>{shelf.error.message}</EmptyState>
      ) : shelf.data.length === 0 ? (
        <EmptyState icon={PackageCheck} title="Shelf is empty">Rolls appear here when QC passes them.</EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {shelf.data.map((g) => (
            <section key={g.order_id} className={cn("flex min-w-0 flex-col border border-border bg-card", !g.order_open && "border-warning")}>
              <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
                <div>
                  <h2 className="text-base">{g.order_code} · {g.buyer_name}</h2>
                  <p className="text-sm text-muted-foreground">
                    {metres(g.on_shelf_m)} on shelf · {metres(g.shipped_m)} of {metres(g.ordered_m)} shipped
                    {!g.order_open && " · order not open"}
                  </p>
                </div>
                {canLoad && g.order_open && <Button size="lg" onClick={() => setShipOrder(g.order_id)}><Truck /> Ship</Button>}
              </div>
              <Table containerClassName="scroll-panel max-h-80">
                <TableHeader className="sticky top-0 z-10 bg-card">
                  <TableRow>
                    <TableHead>Roll</TableHead>
                    <TableHead>Shade</TableHead>
                    <TableHead>Where</TableHead>
                    <TableHead className="text-right">Metres</TableHead>
                    <TableHead className="text-right">Days</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {g.rolls.map((r) => (
                    <TableRow key={r.id} className="[&_td]:h-11">
                      <TableCell>
                        <Link href={`/qc/rolls/${r.id}`} className="num font-semibold hover:text-ember">{r.code}</Link>
                        {r.dispatch_code && <span className="ml-2 text-xs text-info">on {r.dispatch_code}</span>}
                      </TableCell>
                      <TableCell>{r.shade_band ?? "—"}</TableCell>
                      <TableCell className="num">{r.location}</TableCell>
                      <TableCell className="tabular text-right">{metres(r.length_m)}</TableCell>
                      <TableCell className={cn("tabular text-right", r.days_on_shelf > 7 && "font-semibold text-warning")}>{r.days_on_shelf}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </section>
          ))}
        </div>
      )}
      <Dialog open={shipOrder !== null} onOpenChange={(o) => !o && setShipOrder(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>New dispatch</DialogTitle>
            <DialogDescription>Vehicle can be added before the truck leaves.</DialogDescription>
          </DialogHeader>
          {shipOrder !== null && <CreateDispatchForm orderId={shipOrder} onDone={(id) => router.push(`/dispatch/${id}`)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
