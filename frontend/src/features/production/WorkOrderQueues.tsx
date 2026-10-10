"use client";

import { AlertTriangle, ArrowDown, ArrowUp, ClipboardList, Play, Square, Undo2 } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { date, humanize, kg, metres } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";

import { type BoardTile, type OpenWorkOrder, pct, type Stage, useBoard, useFloorAction, useOpenWorkOrders } from "./api";
import { selectClass } from "./FloorForms";

const STAGES: Stage[] = ["spinning", "weaving", "dyeing"];
const qtyOf = (wo: OpenWorkOrder, v: string) => (wo.unit === "kg" ? kg(v) : metres(v));

function JobLine({ wo }: { wo: OpenWorkOrder }) {
  return (
    <div className="min-w-0">
      <p className="truncate font-medium">
        {wo.code} · {wo.order_code}
        {wo.roll_id && " · rework"}
      </p>
      <p className="text-xs text-muted-foreground tabular">
        {qtyOf(wo, wo.produced)} of {qtyOf(wo, wo.planned_qty)} ({pct(wo.produced, wo.planned_qty)}%) · due {date(wo.deadline)}
      </p>
    </div>
  );
}

function ActionError({ errors }: { errors: Record<string, string> }) {
  const message = Object.values(errors)[0];
  return message ? (
    <p role="alert" className="text-sm text-danger">
      {message}
    </p>
  ) : null;
}

// one waiting job: pick a machine of its stage and queue it
function WaitingRow({ wo, machines }: { wo: OpenWorkOrder; machines: BoardTile[] }) {
  const [machineId, setMachineId] = useState("");
  const queue = useFloorAction<{ id: number; machine_id: number }>((b) => `/production/work-orders/${b.id}/queue`);
  const usable = machines.filter((m) => m.type === wo.stage);
  return (
    <li className="grid gap-2 rounded-lg border bg-card p-3">
      <JobLine wo={wo} />
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (machineId) queue.mutate({ id: wo.id, machine_id: Number(machineId) });
        }}
      >
        <select aria-label={`Machine for ${wo.code}`} required value={machineId} onChange={(e) => setMachineId(e.target.value)} className={selectClass}>
          <option value="">Pick a {wo.stage} machine</option>
          {usable.map((m) => (
            <option key={m.machine_id} value={m.machine_id} disabled={m.status === "breakdown" || m.status === "maintenance"}>
              {m.code} · {humanize(m.status)}
              {m.queued ? ` · ${m.queued} queued` : ""}
            </option>
          ))}
        </select>
        <Button type="submit" className="h-12" disabled={!machineId || queue.isPending}>
          Queue
        </Button>
      </form>
      <ActionError errors={queue.errors} />
    </li>
  );
}

function MoveDialog({ wo, machines, onClose }: { wo: OpenWorkOrder | null; machines: BoardTile[]; onClose: () => void }) {
  const [machineId, setMachineId] = useState("");
  const [reason, setReason] = useState("");
  const move = useFloorAction<{ id: number; machine_id: number; reason: string }>((b) => `/production/work-orders/${b.id}/move`);
  const targets = wo ? machines.filter((m) => m.type === wo.stage && m.machine_id !== wo.machine_id) : [];
  return (
    <Dialog open={wo !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Move {wo?.code}</DialogTitle>
          <DialogDescription>Send this job to another {wo?.stage} machine. The reason is kept in the activity log.</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!wo || !machineId || !reason.trim()) return;
            move.mutate({ id: wo.id, machine_id: Number(machineId), reason: reason.trim() }, { onSuccess: onClose });
          }}
        >
          <FormField name="machine_id" label="To machine" required error={move.errors.machine_id}>
            <select id="machine_id" required value={machineId} onChange={(e) => setMachineId(e.target.value)} className={selectClass}>
              <option value="">Pick a machine</option>
              {targets.map((m) => (
                <option key={m.machine_id} value={m.machine_id} disabled={m.status === "breakdown" || m.status === "maintenance"}>
                  {m.code} · {humanize(m.status)}
                </option>
              ))}
            </select>
          </FormField>
          <FormField name="reason" label="Reason" required error={move.errors.reason} hint="e.g. LM-03 down, motor burnt">
            <Input id="reason" required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} className="h-12" />
          </FormField>
          {move.errors.form && <p role="alert" className="text-sm text-danger">{move.errors.form}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!machineId || !reason.trim() || move.isPending}>
              {move.isPending ? "Moving…" : "Move job"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// one machine: its running or paused job, then its queue in order
function MachineQueue({ machine, jobs, onMove }: { machine: BoardTile; jobs: OpenWorkOrder[]; onMove: (wo: OpenWorkOrder) => void }) {
  const queued = jobs.filter((w) => w.status === "queued").sort((a, b) => (a.queue_position ?? 0) - (b.queue_position ?? 0));
  const active = jobs.filter((w) => w.status === "running" || w.status === "paused");
  const reorder = useFloorAction<{ work_order_ids: number[] }>(() => `/production/machines/${machine.machine_id}/queue`, "PUT");
  const act = useFloorAction<{ id: number; verb: string }>((b) => `/production/work-orders/${b.id}/${b.verb}`);

  function swap(i: number, j: number) {
    const ids = queued.map((w) => w.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder.mutate({ work_order_ids: ids });
  }

  return (
    <section className="rounded-lg border bg-card" aria-label={`${machine.code} queue`}>
      <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h3 className="font-semibold">{machine.code}</h3>
        <StatusBadge status={machine.status} />
      </header>
      <ul className="divide-y">
        {active.map((wo) => (
          <li key={wo.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
            <div className="min-w-0 flex-1">
              <JobLine wo={wo} />
            </div>
            <StatusBadge status={wo.status} />
            {wo.status === "paused" ? (
              <>
                <Button size="lg" variant="outline" onClick={() => onMove(wo)}>
                  Move
                </Button>
                <Button size="lg" onClick={() => act.mutate({ id: wo.id, verb: "start" })} disabled={act.isPending}>
                  <Play /> Resume
                </Button>
              </>
            ) : (
              <Button size="lg" variant="outline" onClick={() => act.mutate({ id: wo.id, verb: "finish" })} disabled={act.isPending}>
                <Square /> Finish
              </Button>
            )}
          </li>
        ))}
        {queued.map((wo, i) => (
          <li key={wo.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
            <span className="w-6 text-center text-sm text-muted-foreground tabular">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <JobLine wo={wo} />
            </div>
            <div className="flex gap-1">
              <Button size="icon-lg" variant="ghost" aria-label={`Move ${wo.code} up`} disabled={i === 0 || reorder.isPending} onClick={() => swap(i, i - 1)}>
                <ArrowUp />
              </Button>
              <Button size="icon-lg" variant="ghost" aria-label={`Move ${wo.code} down`} disabled={i === queued.length - 1 || reorder.isPending} onClick={() => swap(i, i + 1)}>
                <ArrowDown />
              </Button>
              <Button size="icon-lg" variant="ghost" aria-label={`Take ${wo.code} off the queue`} disabled={act.isPending} onClick={() => act.mutate({ id: wo.id, verb: "unqueue" })}>
                <Undo2 />
              </Button>
              <Button size="lg" variant="outline" onClick={() => onMove(wo)}>
                Move
              </Button>
              <Button size="lg" disabled={active.length > 0 || act.isPending} onClick={() => act.mutate({ id: wo.id, verb: "start" })}>
                <Play /> Start
              </Button>
            </div>
          </li>
        ))}
        {active.length + queued.length === 0 && <li className="px-4 py-3 text-sm text-muted-foreground">Nothing queued.</li>}
      </ul>
      <div className="px-4 empty:hidden">
        <ActionError errors={{ ...reorder.errors, ...act.errors }} />
      </div>
    </section>
  );
}

// R7: which job is on which machine, queue order, start / move / finish
export function WorkOrderQueues() {
  useSSE(["machines"]);
  const jobs = useOpenWorkOrders();
  const board = useBoard();
  const [moving, setMoving] = useState<OpenWorkOrder | null>(null);
  const machines = board.data?.machines ?? [];
  const all = jobs.data ?? [];
  const error = jobs.error ?? board.error;

  if (error) {
    return (
      <>
        <PageHeader title="Work orders" />
        <EmptyState icon={AlertTriangle} title="Could not load work orders" action={<Button variant="outline" onClick={() => { jobs.refetch(); board.refetch(); }}>Try again</Button>}>
          {error.message}
        </EmptyState>
      </>
    );
  }

  return (
    <>
      <PageHeader title="Work orders" description="Queue jobs on machines of the right type. A broken machine takes no new work." />
      {jobs.isPending || board.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : all.length === 0 ? (
        <EmptyState icon={ClipboardList} title="No open work orders">
          Work orders appear here when sales confirms an order.
        </EmptyState>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[22rem_1fr]">
          <section aria-label="Waiting">
            <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Waiting</h2>
            {all.some((w) => w.status === "waiting") ? (
              <ul className="grid gap-3">
                {all
                  .filter((w) => w.status === "waiting")
                  .map((wo) => (
                    <WaitingRow key={wo.id} wo={wo} machines={machines} />
                  ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Every open job is on a machine.</p>
            )}
          </section>
          <div className="grid gap-6">
            {STAGES.map((stage) => {
              const ofStage = machines.filter((m) => m.type === stage);
              return ofStage.length ? (
                <section key={stage} aria-label={humanize(stage)}>
                  <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{humanize(stage)}</h2>
                  <div className="grid gap-4 xl:grid-cols-2">
                    {ofStage.map((m) => (
                      <MachineQueue key={m.machine_id} machine={m} jobs={all.filter((w) => w.machine_id === m.machine_id)} onMove={setMoving} />
                    ))}
                  </div>
                </section>
              ) : null;
            })}
          </div>
        </div>
      )}
      <MoveDialog key={moving?.id} wo={moving} machines={machines} onClose={() => setMoving(null)} />
    </>
  );
}
