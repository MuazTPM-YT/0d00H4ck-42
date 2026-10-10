"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Paged } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Column<T> = { key: string; header: string; cell: (row: T) => ReactNode; className?: string };

// list view with loading, empty, error and pagination; scrolls sideways on phones
export function DataTable<T extends { id: number }>({
  columns,
  query,
  offset,
  limit,
  onOffsetChange,
  onRowClick,
  empty,
}: {
  columns: Column<T>[];
  query: UseQueryResult<Paged<T>>;
  offset: number;
  limit: number;
  onOffsetChange: (offset: number) => void;
  onRowClick?: (row: T) => void;
  empty: ReactNode;
}) {
  if (query.isError) {
    return (
      <EmptyState icon={AlertTriangle} title="Could not load this list" action={<Button variant="outline" onClick={() => query.refetch()}>Try again</Button>}>
        {query.error.message}
      </EmptyState>
    );
  }
  if (query.data && query.data.total === 0) return <>{empty}</>;

  const total = query.data?.total ?? 0;
  return (
    <div className="overflow-hidden rounded-2xl bg-card shadow-card">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead key={c.key} className={c.className}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending
              ? Array.from({ length: 5 }, (_, i) => (
                  <TableRow key={i}>
                    {columns.map((c) => (
                      <TableCell key={c.key}>
                        <Skeleton className="h-4 w-full max-w-32" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              : query.data.items.map((row) => (
                  <TableRow
                    key={row.id}
                    onClick={onRowClick && (() => onRowClick(row))}
                    tabIndex={onRowClick ? 0 : undefined}
                    onKeyDown={onRowClick && ((e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onRowClick(row)))}
                    className={cn(onRowClick && "cursor-pointer outline-none focus-visible:bg-info-soft active:bg-muted")}
                  >
                    {columns.map((c) => (
                      <TableCell key={c.key} className={c.className}>
                        {c.cell(row)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 px-4 py-2.5 text-[0.88rem] text-muted-foreground">
        <span className="tabular">
          {total === 0 ? "…" : `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={offset === 0} onClick={() => onOffsetChange(Math.max(0, offset - limit))}>
            <ChevronLeft />
          </Button>
          <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={offset + limit >= total} onClick={() => onOffsetChange(offset + limit)}>
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
