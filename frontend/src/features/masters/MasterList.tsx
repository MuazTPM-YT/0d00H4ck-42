"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { type ReactNode, useState } from "react";

import { type Column, DataTable } from "@/components/layout/DataTable";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, type Paged, qs } from "@/lib/api";

import type { Row } from "./config";

const LIMIT = 20;

// list + search + add/edit dialog, shared by every master screen
export function MasterList({
  path,
  title,
  singular,
  description,
  columns,
  hasActive,
  renderForm,
}: {
  path: string;
  title: string;
  singular: string;
  description: string;
  columns: Column<Row>[];
  hasActive: boolean;
  renderForm: (row: Row | null, done: () => void) => ReactNode;
}) {
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Row | null | undefined>(undefined); // undefined = closed, null = new

  const active = hasActive && !showInactive ? true : undefined;
  const query = useQuery({
    queryKey: ["masters", path, { q, active, offset }],
    queryFn: () => api<Paged<Row>>(`/masters/${path}${qs({ q, active, limit: LIMIT, offset })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title={title}
        description={description}
        actions={
          <Button onClick={() => setEditing(null)}>
            <Plus /> Add {singular}
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative sm:max-w-xs sm:flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            aria-label={`Search ${title.toLowerCase()}`}
            placeholder="Search"
            maxLength={100}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            className="pl-9"
          />
        </div>
        {hasActive && (
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={showInactive} onChange={(e) => { setShowInactive(e.target.checked); setOffset(0); }} className="size-4 accent-primary" />
            Show inactive too
          </label>
        )}
      </div>

      <DataTable
        columns={columns}
        query={query}
        offset={offset}
        limit={LIMIT}
        onOffsetChange={setOffset}
        onRowClick={setEditing}
        empty={
          <EmptyState title={q ? `No ${title.toLowerCase()} match “${q}”` : `No ${title.toLowerCase()} yet`} action={!q && <Button onClick={() => setEditing(null)}><Plus /> Add {singular}</Button>}>
            {q ? "Try a shorter search." : description}
          </EmptyState>
        }
      />

      <Dialog open={editing !== undefined} onOpenChange={(open) => !open && setEditing(undefined)}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${singular}` : `Add ${singular}`}</DialogTitle>
            <DialogDescription>Fields marked * are required.</DialogDescription>
          </DialogHeader>
          {editing !== undefined && renderForm(editing, () => setEditing(undefined))}
        </DialogContent>
      </Dialog>
    </>
  );
}
