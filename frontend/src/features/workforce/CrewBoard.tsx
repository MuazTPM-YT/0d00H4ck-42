"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, UserMinus, Users } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Paged } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";
import { todayIST, useFloorAction, useMachines } from "@/features/production/api";
import { selectClass } from "@/features/production/FloorForms";

type Shift = { id: number; code: string; name: string; start_time: string; end_time: string };
type Worker = { id: number; code: string; name: string };
type Crew = { id: number; worker_id: number; worker_name: string; machine_id: number; machine_code: string; from_at: string; to_at: string | null };
type Attendance = { id: number; worker_id: number; status: "present" | "absent" | "half_day"; source: "crew" | "manual" };

const STATUSES = ["present", "half_day", "absent"] as const;
const time = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" });

function AttendanceDialog({ worker, day, shiftId, current, onClose }: { worker: Worker | null; day: string; shiftId: number; current?: string; onClose: () => void }) {
  const [status, setStatus] = useState(current ?? "present");
  const [reason, setReason] = useState("");
  const save = useFloorAction<object>(() => "/workforce/attendance", "PUT");
  return (
    <Dialog open={worker !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Attendance · {worker?.name}</DialogTitle>
          <DialogDescription>Manual entry for staff off the machines, or a correction. The reason is kept in the activity log.</DialogDescription>
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
            {STATUSES.map((s) => (
              <Button key={s} type="button" role="radio" aria-checked={status === s} variant={status === s ? "default" : "outline"} className="h-12" onClick={() => setStatus(s)}>
                {humanize(s)}
              </Button>
            ))}
          </div>
          <FormField name="reason" label="Reason" required error={save.errors.reason} hint="e.g. office staff, called in sick">
            <Input id="reason" required maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} className="h-12" />
          </FormField>
          {(save.errors.form ?? save.errors.date) && <p role="alert" className="text-sm text-danger">{save.errors.form ?? save.errors.date}</p>}
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

// R9 + R20: who runs which machine this shift; attendance follows from it
export function CrewBoard() {
  useSSE(["machines"]);
  const current = useQuery({ queryKey: ["machines", "current-shift"], queryFn: () => api<{ date: string; shift_id: number }>("/workforce/current-shift") });
  const shifts = useQuery({ queryKey: ["masters", "shifts", "all"], queryFn: () => api<Paged<Shift>>("/masters/shifts?limit=50") });
  const workers = useQuery({ queryKey: ["masters", "workers", "active"], queryFn: () => api<Paged<Worker>>("/masters/workers?active=true&limit=200") });
  const machines = useMachines();

  const [picked, setPicked] = useState<{ date: string; shift: number } | null>(null);
  const day = picked?.date ?? current.data?.date ?? todayIST();
  const shiftId = picked?.shift ?? current.data?.shift_id ?? 0;

  const crew = useQuery({
    queryKey: ["machines", "crew", day, shiftId],
    queryFn: () => api<Crew[]>(`/workforce/crew?date=${day}&shift_id=${shiftId}`),
    enabled: shiftId > 0,
  });
  const attendance = useQuery({
    queryKey: ["machines", "attendance", day, shiftId],
    queryFn: () => api<Paged<Attendance>>(`/workforce/attendance?date=${day}&shift_id=${shiftId}&limit=200`),
    enabled: shiftId > 0,
  });

  const [workerId, setWorkerId] = useState("");
  const [machineId, setMachineId] = useState("");
  const [marking, setMarking] = useState<Worker | null>(null);
  const assign = useFloorAction<object>(() => "/workforce/crew");
  const end = useFloorAction<{ id: number }>((b) => `/workforce/crew/${b.id}/end`);

  const queries = [current, shifts, workers, machines, crew, attendance];
  const failed = queries.find((q) => q.isError);
  const loading = queries.some((q) => q.isPending && q.fetchStatus !== "idle");
  const open = (crew.data ?? []).filter((c) => !c.to_at);
  const onMachine = new Map(open.map((c) => [c.worker_id, c]));
  const status = new Map((attendance.data?.items ?? []).map((a) => [a.worker_id, a]));
  const moving = onMachine.get(Number(workerId));

  return (
    <>
      <PageHeader title="Crew and attendance" description="Put workers on machines at shift start. Attendance fills itself from this." />

      <div className="mb-6 flex flex-wrap gap-3">
        <FormField name="day" label="Date">
          <Input id="day" type="date" max={todayIST()} value={day} onChange={(e) => e.target.value && setPicked({ date: e.target.value, shift: shiftId })} className="h-12 w-44" />
        </FormField>
        <FormField name="shift" label="Shift">
          <select id="shift" value={shiftId} onChange={(e) => setPicked({ date: day, shift: Number(e.target.value) })} className={`${selectClass} w-48`}>
            {(shifts.data?.items ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)})
              </option>
            ))}
          </select>
        </FormField>
      </div>

      {failed ? (
        <EmptyState icon={AlertTriangle} title="Could not load the crew" action={<Button variant="outline" onClick={() => queries.forEach((q) => q.refetch())}>Try again</Button>}>
          {failed.error?.message}
        </EmptyState>
      ) : loading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <section className="grid gap-4 rounded-lg border bg-card p-4" aria-label="Assign">
            <h2 className="font-semibold">{moving ? "Move worker" : "Put a worker on a machine"}</h2>
            <form
              className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
              onSubmit={(e) => {
                e.preventDefault();
                if (!workerId || !machineId) return;
                assign.mutate(
                  { date: day, shift_id: shiftId, worker_id: Number(workerId), machine_id: Number(machineId) },
                  { onSuccess: () => { setWorkerId(""); setMachineId(""); } },
                );
              }}
            >
              <FormField name="worker_id" label="Worker" required error={assign.errors.worker_id}>
                <select id="worker_id" required value={workerId} onChange={(e) => setWorkerId(e.target.value)} className={selectClass}>
                  <option value="">Pick a worker</option>
                  {(workers.data?.items ?? []).map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} {onMachine.has(w.id) ? `· on ${onMachine.get(w.id)!.machine_code}` : ""}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField name="machine_id" label="Machine" required error={assign.errors.machine_id}>
                <select id="machine_id" required value={machineId} onChange={(e) => setMachineId(e.target.value)} className={selectClass}>
                  <option value="">Pick a machine</option>
                  {(machines.data?.items ?? []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.code} · {m.name}
                    </option>
                  ))}
                </select>
              </FormField>
              <Button type="submit" className="h-12" disabled={!workerId || !machineId || assign.isPending}>
                {moving ? "Move" : "Assign"}
              </Button>
            </form>
            {(assign.errors.form ?? assign.errors.date ?? assign.errors.shift_id) && (
              <p role="alert" className="text-sm text-danger">
                {assign.errors.form ?? assign.errors.date ?? assign.errors.shift_id}
              </p>
            )}

            {(crew.data ?? []).length === 0 ? (
              <EmptyState icon={Users} title="Nobody assigned yet">
                Pick a worker and a machine above.
              </EmptyState>
            ) : (
              <ul className="divide-y rounded-md border">
                {(crew.data ?? []).map((c) => (
                  <li key={c.id} className={`flex items-center gap-3 px-3 py-2 ${c.to_at ? "text-muted-foreground" : ""}`}>
                    <span className="w-16 shrink-0 font-medium">{c.machine_code}</span>
                    <span className="min-w-0 flex-1 truncate">{c.worker_name}</span>
                    <span className="text-xs tabular">
                      {time(c.from_at)}–{c.to_at ? time(c.to_at) : "now"}
                    </span>
                    {!c.to_at && (
                      <Button size="icon-lg" variant="ghost" aria-label={`Take ${c.worker_name} off ${c.machine_code}`} disabled={end.isPending} onClick={() => end.mutate({ id: c.id })}>
                        <UserMinus />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {end.errors.form && <p role="alert" className="text-sm text-danger">{end.errors.form}</p>}
          </section>

          <section className="rounded-lg border bg-card" aria-label="Attendance">
            <h2 className="border-b px-4 py-3 font-semibold">Attendance</h2>
            <ul className="divide-y">
              {(workers.data?.items ?? []).map((w) => {
                const row = status.get(w.id);
                return (
                  <li key={w.id}>
                    <button type="button" onClick={() => setMarking(w)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-accent focus-visible:bg-accent focus-visible:outline-none">
                      <span className="w-14 shrink-0 text-xs text-muted-foreground">{w.code}</span>
                      <span className="min-w-0 flex-1 truncate">{w.name}</span>
                      {row ? <StatusBadge status={row.status} /> : <span className="text-xs text-muted-foreground">Not marked</span>}
                      {row && <span className="w-12 text-xs text-muted-foreground">{row.source}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      )}
      <AttendanceDialog key={marking?.id} worker={marking} day={day} shiftId={shiftId} current={marking ? status.get(marking.id)?.status : undefined} onClose={() => setMarking(null)} />
    </>
  );
}
