"use client";

import { AlertTriangle, ClipboardList, Factory, Users } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { humanize } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { MACHINE_STATUSES, useBoard, useNow } from "./api";
import { MachinePanel } from "./MachinePanel";
import { MachineTile, STATUS_BAR } from "./MachineTile";

const GRID = "grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

// R8: every machine at a glance, pushed live over SSE topic "machines"
export function FloorBoard({ top }: { top?: ReactNode }) {
  useSSE(["machines", "quality"]);
  const board = useBoard();
  const now = useNow();
  const [openId, setOpenId] = useState<number | null>(null);
  const tiles = board.data?.machines ?? [];
  const open = tiles.find((t) => t.machine_id === openId) ?? null;
  const counts = Object.fromEntries(MACHINE_STATUSES.map((s) => [s, tiles.filter((t) => t.status === s).length]));

  return (
    <>
      <PageHeader
        title="Floor board"
        description={board.data ? `Shift ${board.data.shift_code ?? "—"} · updates live` : "Every machine, live"}
        actions={
          <>
            <Button variant="outline" asChild>
              <Link href="/floor/crew">
                <Users /> Crew
              </Link>
            </Button>
            <Button asChild>
              <Link href="/floor/work-orders">
                <ClipboardList /> Work orders
              </Link>
            </Button>
          </>
        }
      />
      {top}

      {board.isError ? (
        <EmptyState icon={AlertTriangle} title="Could not load the floor" action={<Button variant="outline" onClick={() => board.refetch()}>Try again</Button>}>
          {board.error.message}
        </EmptyState>
      ) : board.isPending ? (
        <div className={GRID}>
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-44 rounded-lg" />
          ))}
        </div>
      ) : tiles.length === 0 ? (
        <EmptyState icon={Factory} title="No machines yet">
          The owner adds machines under Masters.
        </EmptyState>
      ) : (
        <>
          <ul className="mb-4 flex flex-wrap gap-x-4 gap-y-2 text-sm" aria-label="Machines by status">
            {MACHINE_STATUSES.filter((s) => counts[s]).map((s) => (
              <li key={s} className="flex items-center gap-2">
                <span className={`dot size-2.5 ${STATUS_BAR[s]}`} aria-hidden />
                {humanize(s)} <span className="font-semibold tabular">{counts[s]}</span>
              </li>
            ))}
          </ul>
          <div className={GRID}>
            {tiles.map((t) => (
              <MachineTile key={t.machine_id} tile={t} now={now} onOpen={() => setOpenId(t.machine_id)} />
            ))}
          </div>
        </>
      )}

      <MachinePanel tile={open} onClose={() => setOpenId(null)} />
    </>
  );
}
