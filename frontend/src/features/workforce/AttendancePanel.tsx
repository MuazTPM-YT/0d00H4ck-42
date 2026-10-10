"use client";

import { Select } from "@/components/ui/select";

import { UserMinus, Users } from "lucide-react";
import { useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type Machine, useFloorAction } from "@/features/production/api";
import { selectClass } from "@/features/production/FloorForms";

import { ATTENDANCE, type AttendanceStatus, clock, type RosterRow, type RosterStatus, type Worker } from "./api";

export type Filter = "all" | RosterStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "on_machine", label: "On a machine" },
  { key: "free", label: "Free" },
  { key: "absent", label: "Absent" },
  { key: "unmarked", label: "Not marked" },
];

const MARK: Record<AttendanceStatus, { short: string; on: string }> = {
  present: { short: "P", on: "bg-success-soft text-success border-success/40" },
  half_day: { short: "H", on: "bg-warning-soft text-warning border-warning/40" },
  absent: { short: "A", on: "bg-danger-soft text-danger border-danger/40" },
};

const REASONS = ["Roll call", "Called in sick", "On leave", "Office staff", "Left early"];

export const compactSelect = cn(selectClass, "h-9 min-w-0 text-sm");

// machine picker grouped by stage; the machine they already sit on can't be picked
export function MachineOptions({ machines, except }: { machines: Machine[]; except?: number }) {
  const stages = [...new Set(machines.map((m) => m.type))];
  return stages.map((stage) => (
    <optgroup key={stage} label={humanize(stage)}>
      {machines
        .filter((m) => m.type === stage)
        .map((m) => (
          <option key={m.id} value={m.id} disabled={m.id === except}>
            {m.code} · {m.name}
          </option>
        ))}
    </optgroup>
  ));
}

// manual entry or correction; the reason lands in the activity log, so it is never optional
export function AttendanceDialog({
  worker,
  day,
  shiftId,
  initial,
  current,
  onClose,
}: {
  worker: Worker | null;
  day: string;
  shiftId: number;
  initial?: AttendanceStatus;
  current?: AttendanceStatus;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<AttendanceStatus>(initial ?? current ?? "present");
  const [reason, setReason] = useState("");
  const save = useFloorAction<object>(() => "/workforce/attendance", "PUT");
  return (
    <Dialog open={worker !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="sm:max-w-md"
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          document.getElementById("reason")?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>Attendance · {worker?.name}</DialogTitle>
          <DialogDescription>
            {current ? `Now ${humanize(current)}. ` : "Not marked yet. "}
            The reason is kept in the activity log.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!worker || !reason.trim()) return;
            save.mutate({ date: day, shift_id: shiftId, worker_id: worker.id, status, reason: reason.trim() }, { onSuccess: onClose });
          }}
        >
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Status">
            {ATTENDANCE.map((s) => (
              <Button key={s} type="button" role="radio" aria-checked={status === s} variant={status === s ? "default" : "outline"} className="h-12" onClick={() => setStatus(s)}>
                {humanize(s)}
              </Button>
            ))}
          </div>
          <FormField name="reason" label="Reason" required error={save.errors.reason} hint="Press Enter to save">
            <Input id="reason" required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} className="h-12" />
          </FormField>
          <div className="flex flex-wrap gap-1.5" aria-label="Common reasons">
            {REASONS.map((r) => (
              <button key={r} type="button" onClick={() => setReason(r)} className={cn("label border border-border px-2 py-1 normal-case tracking-[0.04em] hover:border-ember hover:text-ember", reason === r && "border-ember text-ember")}>
                {r}
              </button>
            ))}
          </div>
          {(save.errors.form ?? save.errors.date ?? save.errors.worker_id) && (
            <p role="alert" className="text-sm text-danger">
              {save.errors.form ?? save.errors.date ?? save.errors.worker_id}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!reason.trim() || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function StatusLine({ row }: { row: RosterRow }) {
  if (row.crew)
    return (
      <span className="text-ember">
        On {row.crew.machine_code} <span className="text-muted-foreground">since {clock(row.crew.from_at)}</span>
      </span>
    );
  if (row.status === "free") return <span>{row.attendance?.status === "half_day" ? "Half day · free" : "Present · free"}</span>;
  if (row.status === "absent") return <span className="text-danger">Absent</span>;
  return <span>Not marked</span>;
}

// one worker: who they are, where they are, and the two things you do to them
function Row({
  row,
  day,
  shiftId,
  machines,
  selected,
  onSelect,
  onMark,
  onAssigned,
}: {
  row: RosterRow;
  day: string;
  shiftId: number;
  machines: Machine[];
  selected: boolean;
  onSelect: () => void;
  onMark: (status: AttendanceStatus) => void;
  onAssigned: () => void;
}) {
  const [machineId, setMachineId] = useState("");
  const assign = useFloorAction<object>(() => "/workforce/crew");
  const end = useFloorAction<{ id: number }>((b) => `/workforce/crew/${b.id}/end`);
  const { worker, crew, attendance } = row;
  const error = assign.errors.machine_id ?? assign.errors.form ?? assign.errors.worker_id ?? assign.errors.date ?? end.errors.form;

  function submit() {
    if (!machineId) return;
    assign.mutate(
      { date: day, shift_id: shiftId, worker_id: worker.id, machine_id: Number(machineId) },
      { onSuccess: () => { setMachineId(""); onAssigned(); } },
    );
  }

  return (
    <li id={`worker-${worker.id}`} className={cn("border-l-2 border-l-transparent px-4 py-2.5", selected && "border-l-ember bg-accent")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <button type="button" onClick={onSelect} aria-pressed={selected} className="min-w-36 flex-1 basis-40 text-left outline-none focus-visible:ring-2 focus-visible:ring-ember">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate font-medium">{worker.name}</span>
            <span className="num shrink-0 text-xs text-muted-foreground">{worker.code}</span>
          </span>
          <span className="block truncate text-[0.82rem] text-muted-foreground">
            <StatusLine row={row} />
            {attendance?.source === "manual" && <span className="label ml-2 normal-case">· manual</span>}
          </span>
        </button>

        <form
          className="flex items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Select
            id={`assign-${worker.id}`}
            aria-label={crew ? `Move ${worker.name} to` : `Put ${worker.name} on`}
            value={machineId}
            onChange={(e) => setMachineId(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit();
              } else if (e.key === "Escape" && selected) {
                onSelect();
              }
            }}
            className={cn(compactSelect, "w-36")}
          >
            <option value="">{crew ? "Move to…" : "Machine…"}</option>
            <MachineOptions machines={machines} except={crew?.machine_id} />
          </Select>
          <Button type="submit" size="sm" variant="outline" disabled={!machineId || assign.isPending}>
            {crew ? "Move" : "Assign"}
          </Button>
          {crew && (
            <Button type="button" size="icon-sm" variant="ghost" aria-label={`Take ${worker.name} off ${crew.machine_code}`} title="Release" disabled={end.isPending} onClick={() => end.mutate({ id: crew.id })}>
              <UserMinus />
            </Button>
          )}
        </form>

        <div className="flex" role="group" aria-label={`Attendance for ${worker.name}`}>
          {ATTENDANCE.map((s) => {
            const on = attendance?.status === s;
            // on a machine and absent can't both be true; release first
            const blocked = s === "absent" && !!crew;
            return (
              <button
                key={s}
                type="button"
                aria-pressed={on}
                aria-label={humanize(s)}
                title={blocked ? "Release from the machine first" : humanize(s)}
                disabled={blocked}
                onClick={() => !on && onMark(s)}
                className={cn(
                  "num -ml-px size-9 border border-border text-[0.8rem] font-medium first:ml-0 hover:z-10 hover:border-ember hover:text-ember focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ember focus-visible:outline-none disabled:pointer-events-none disabled:opacity-30",
                  on && MARK[s].on,
                )}
              >
                {MARK[s].short}
              </button>
            );
          })}
        </div>
      </div>
      {error && (
        <p role="alert" className="mt-1.5 text-sm text-danger">
          {error}
        </p>
      )}
    </li>
  );
}

// R20: everyone on the roll for this shift, filterable by where they stand
export function AttendancePanel({
  rows,
  filter,
  onFilter,
  searching,
  day,
  shiftId,
  machines,
  selectedId,
  onSelect,
  onMark,
  onAssigned,
}: {
  rows: RosterRow[];
  filter: Filter;
  onFilter: (f: Filter) => void;
  searching: boolean;
  day: string;
  shiftId: number;
  machines: Machine[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onMark: (worker: Worker, status: AttendanceStatus) => void;
  onAssigned: () => void;
}) {
  const counts = { all: rows.length, on_machine: 0, free: 0, absent: 0, unmarked: 0 } as Record<Filter, number>;
  rows.forEach((r) => counts[r.status]++);
  const shown = filter === "all" ? rows : rows.filter((r) => r.status === filter);

  return (
    <section className="min-w-0 border border-border bg-card" aria-label="Roster">
      <header className="grid gap-3 border-b border-border px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="eyebrow text-foreground">Roster</h2>
          <span className="label">{searching ? "Search results" : "This shift"}</span>
        </div>
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter roster">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => onFilter(f.key)}
              className={cn(
                "label flex items-center gap-2 border border-border px-2.5 py-1.5 hover:border-ember hover:text-ember focus-visible:ring-2 focus-visible:ring-ember focus-visible:outline-none",
                filter === f.key && "border-foreground bg-foreground text-background hover:text-background",
              )}
            >
              {f.label}
              <span className="num">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </header>
      {shown.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-6 py-12 text-center text-muted-foreground">
          <Users className="size-5 text-ember" aria-hidden />
          <p>{searching ? "No worker matches that search." : filter === "all" ? "No active workers. Add them under Masters." : "Nobody in this group."}</p>
        </div>
      ) : (
        <ul className="scroll-panel max-h-[34rem] divide-y divide-border lg:max-h-[calc(100dvh-15rem)]">
          {shown.map((r) => (
            <Row
              key={r.worker.id}
              row={r}
              day={day}
              shiftId={shiftId}
              machines={machines}
              selected={selectedId === r.worker.id}
              onSelect={() => onSelect(selectedId === r.worker.id ? null : r.worker.id)}
              onMark={(s) => onMark(r.worker, s)}
              onAssigned={onAssigned}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
