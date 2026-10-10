"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { kg } from "@/lib/format";

import { ErrorText } from "@/features/inventory/ui";

import type { Allocation } from "./types";

// per recipe line: needed, reserved, issued, short, and which lots hold it.
// Self-contained so the order detail page (/orders/[id], tracking) can drop it in.
export function OrderYarnPanel({ orderId }: { orderId: number }) {
  const qc = useQueryClient();
  const role = useMe().data?.role;
  const alloc = useQuery({ queryKey: ["orders", orderId, "allocation"], queryFn: () => api<Allocation>(`/orders/${orderId}/allocation`) });
  const reserve = useMutation({
    mutationFn: () => api<Allocation>(`/orders/${orderId}/reserve`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData(["orders", orderId, "allocation"], data);
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["stock"] });
    },
  });

  if (alloc.isError) return <ErrorText error={alloc.error} />;
  if (alloc.isPending) return <Skeleton className="h-32 w-full" />;
  const a = alloc.data;
  const canReserve = a.status === "confirmed" && !a.fully_covered && (role === "sales" || role === "owner");

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Yarn for {a.code}</h3>
        {a.fully_covered ? (
          <span className="flex items-center gap-1 text-sm text-success"><CheckCircle2 className="size-4" aria-hidden /> Covered</span>
        ) : (
          <span className="flex items-center gap-1 text-sm text-warning"><AlertTriangle className="size-4" aria-hidden /> Short</span>
        )}
      </div>
      {a.mixed_lots && (
        <p className="rounded-md bg-warning-soft p-3 text-sm text-warning">
          Mixed supplier lots on at least one yarn. Mixing lots can show as barre (streaks across the fabric): weave lots in separate pieces if possible.
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Yarn</th>
              <th className="px-3 py-2 text-right font-medium">Needed</th>
              <th className="px-3 py-2 text-right font-medium">Reserved</th>
              <th className="px-3 py-2 text-right font-medium">Issued</th>
              <th className="px-3 py-2 text-right font-medium">Short</th>
              <th className="px-3 py-2 font-medium">Lots</th>
            </tr>
          </thead>
          <tbody>
            {a.lines.map((l) => (
              <tr key={`${l.count}-${l.colour}`} className="border-t align-top">
                <td className="px-3 py-2 whitespace-nowrap">
                  {l.fibre} {l.count} {l.colour}
                  {!l.yarn_item_id && <div className="text-xs text-danger">Not in yarn masters</div>}
                </td>
                <td className="px-3 py-2 text-right">{kg(l.kg_needed)}</td>
                <td className="px-3 py-2 text-right">{kg(l.kg_reserved)}</td>
                <td className="px-3 py-2 text-right">{kg(l.kg_issued)}</td>
                <td className={Number(l.kg_short) > 0 ? "px-3 py-2 text-right font-semibold text-danger" : "px-3 py-2 text-right"}>{kg(l.kg_short)}</td>
                <td className="px-3 py-2 text-xs">
                  {l.lots.length === 0 ? "—" : l.lots.map((lot) => (
                    <div key={lot.yarn_batch_id} className="whitespace-nowrap">
                      {lot.code} · lot {lot.supplier_lot ?? "—"} · {kg(Number(lot.reserved_kg) > 0 ? lot.reserved_kg : lot.consumed_kg)}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canReserve && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => reserve.mutate()} disabled={reserve.isPending}>Reserve from free stock now</Button>
          <span className="text-xs text-muted-foreground">Use after new yarn is approved.</span>
        </div>
      )}
      <ErrorText error={reserve.error} />
    </section>
  );
}
