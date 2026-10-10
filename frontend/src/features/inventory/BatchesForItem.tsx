"use client";

import { useQuery } from "@tanstack/react-query";

import { StatusBadge } from "@/components/layout/StatusBadge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Paged } from "@/lib/api";
import { date, kg } from "@/lib/format";

import type { Batch, StockRow } from "./types";
import { ErrorText } from "./ui";

// drill-down from a stock row: every batch of that yarn, newest first
export function BatchesForItem({ item, onClose, onOpenBatch }: { item: StockRow | null; onClose: () => void; onOpenBatch: (id: number) => void }) {
  const batches = useQuery({
    queryKey: ["stock", "batches", { yarn_item_id: item?.yarn_item_id }],
    queryFn: () => api<Paged<Batch>>(`/inventory/batches?yarn_item_id=${item!.yarn_item_id}&limit=100`),
    enabled: item !== null,
  });

  return (
    <Sheet open={item !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{item?.label}</SheetTitle>
          <SheetDescription>
            Free {kg(item?.free_kg)} · reserved {kg(item?.reserved_kg)} · on the floor {kg(item?.wip_kg)}
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">
          <ErrorText error={batches.error} />
          {batches.isPending && <Skeleton className="h-40 w-full" />}
          {batches.data?.total === 0 && <p className="text-sm text-muted-foreground">No batches of this yarn yet.</p>}
          <ul className="grid gap-2">
            {batches.data?.items.map((b) => (
              <li key={b.id}>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onOpenBatch(b.id);
                  }}
                  className="flex min-h-12 w-full flex-wrap items-center justify-between gap-2 rounded-md border bg-card p-3 text-left hover:border-primary focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <span className="font-medium tabular">{b.code}</span>
                  <span className="text-sm text-muted-foreground">lot {b.supplier_lot ?? "—"}</span>
                  <span className="tabular">{kg(b.received_kg)}</span>
                  <StatusBadge status={b.status} />
                  <span className="w-full text-xs text-muted-foreground">
                    {b.supplier?.name} · received {date(b.receipt?.confirmed_at ?? b.created_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}
