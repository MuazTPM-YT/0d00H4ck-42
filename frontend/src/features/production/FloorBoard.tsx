"use client";

import { AlertTriangle, ClipboardList, Factory, Users } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { type Stat, StatStrip } from "@/components/layout/StatStrip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { humanize, kg, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { type BoardTile, MACHINE_STATUSES, type MachineStatus, type Stage, useBoard, useNow } from "./api";
import { MachinePanel } from "./MachinePanel";
import { MachineTile, STATUS_BAR } from "./MachineTile";

const GRID = "grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";
const STAGES: { stage: Stage; label: string }[] = [
  { stage: "spinning", label: "Spinning" },
  { stage: "weaving", label: "Weaving" },
  { stage: "dyeing", label: "Dyeing" },
];
const MADE: Record<Stage, string> = { spinning: "Spun today", weaving: "Woven today", dyeing: "Dyed today" };

const sum = (tiles: BoardTile[]) => tiles.reduce((s, t) => s + Number(t.today_output), 0);

// how many machines in each state (tap one to show only those) and today's output by stage
function FloorStrip({ tiles, filter, onFilter }: { tiles: BoardTile[]; filter: MachineStatus | null; onFilter: (s: MachineStatus | null) => void }) {
  const stats: Stat[] = MACHINE_STATUSES.map((s) => {
    const n = tiles.filter((t) => t.status === s).length;
    return {
      key: s,
      label: (
        <>
          <span className={`dot size-2 ${STATUS_BAR[s]}`} aria-hidden />
          {humanize(s)}
        </>
      ),
      value: n,
      pressed: filter === s,
      disabled: !n && filter !== s,
      onPress: () => onFilter(filter === s ? null : s),
    };
  });
  for (const { stage } of STAGES) {
    const of = tiles.filter((t) => t.type === stage);
    if (!of.length) continue;
    const total = sum(of);
    stats.push({ key: stage, label: MADE[stage], value: of[0].unit === "kg" ? kg(total.toFixed(1)) : metres(total.toFixed(0)) });
  }
  return <StatStrip stats={stats} />;
}

// R8: every machine at a glance, pushed live over SSE topic "machines"
export function FloorBoard({ top }: { top?: ReactNode }) {
  useSSE(["machines", "quality"]);
  const board = useBoard();
  const now = useNow();
  const [openId, setOpenId] = useState<number | null>(null);
  const [filter, setFilter] = useState<MachineStatus | null>(null);
  const tiles = board.data?.machines ?? [];
  const open = tiles.find((t) => t.machine_id === openId) ?? null;
  const shown = filter ? tiles.filter((t) => t.status === filter) : tiles;

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
          <FloorStrip tiles={tiles} filter={filter} onFilter={setFilter} />
          {shown.length === 0 ? (
            <EmptyState icon={Factory} title={`No machine is ${humanize(filter ?? "")} now`} action={<Button variant="outline" onClick={() => setFilter(null)}>Show all machines</Button>} />
          ) : (
            <div className="grid gap-8">
              {STAGES.map(({ stage, label }) => {
                const group = shown.filter((t) => t.type === stage);
                if (!group.length) return null;
                return (
                  <section key={stage} aria-label={label} className="grid gap-3">
                    <h2 className="eyebrow">
                      {label}
                      <span className="num">{group.length}</span>
                    </h2>
                    <div className={GRID}>
                      {group.map((t) => (
                        <MachineTile key={t.machine_id} tile={t} now={now} onOpen={() => setOpenId(t.machine_id)} />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}

      <MachinePanel tile={open} onClose={() => setOpenId(null)} />
    </>
  );
}
