"use client";

import { Select } from "@/components/ui/select";

import { AlertTriangle, Cog, Search, UserMinus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSSE } from "@/lib/useSSE";
import { type Machine, todayIST, useFloorAction, useMachines } from "@/features/production/api";
import { selectClass } from "@/features/production/FloorForms";

import { type AttendanceStatus, clock, type Crew, matches, rosterOf, type RosterRow, type Shift, useAttendance, useCrew, useCurrentShift, useShifts, useWorkers, type Worker } from "./api";
import { AttendanceDialog, AttendancePanel, compactSelect, type Filter } from "./AttendancePanel";

const STAGE_ORDER = ["spinning", "weaving", "dyeing"];

// typing in a field or a dialog is open: leave "/" and Esc alone
const busyTarget = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) || !!el.closest("[role=dialog], [role=combobox], [role=listbox]"));

// one machine: who is on it now, who was earlier, and how to put someone on
function MachineCard({
  machine,
  crew,
  roster,
  day,
  shiftId,
  picked,
  query,
  onAssigned,
}: {
  machine: Machine;
  crew: Crew[];
  roster: RosterRow[];
  day: string;
  shiftId: number;
  picked: RosterRow | null;
  query: string;
  onAssigned: () => void;
}) {
  const [workerId, setWorkerId] = useState("");
  const assign = useFloorAction<object>(() => "/workforce/crew");
  const end = useFloorAction<{ id: number }>((b) => `/workforce/crew/${b.id}/end`);
  // an assignment closed at a shift end still to come is on the machine until then
  const onUntil = (c: Crew) => !c.to_at || Date.parse(c.to_at) > Date.now();
  const now = crew.filter(onUntil);
  const earlier = crew.filter((c) => !onUntil(c));
  const error = assign.errors.machine_id ?? assign.errors.worker_id ?? assign.errors.form ?? assign.errors.date ?? assign.errors.shift_id ?? end.errors.form;
  const pickedHere = picked?.crew?.machine_id === machine.id;

  function put(id: number) {
    assign.mutate({ date: day, shift_id: shiftId, worker_id: id, machine_id: machine.id }, { onSuccess: () => { setWorkerId(""); onAssigned(); } });
  }

  // free people first, then the unmarked, then those you'd pull off another machine
  const candidates = roster.filter((r) => r.crew?.machine_id !== machine.id);
  const groups: [string, RosterRow[]][] = [
    ["Free", candidates.filter((r) => r.status === "free")],
    ["Not marked", candidates.filter((r) => r.status === "unmarked")],
    ["On another machine (moves them)", candidates.filter((r) => r.status === "on_machine")],
    ["Marked absent", candidates.filter((r) => r.status === "absent")],
  ];

  return (
    <section className={cn("min-w-0 border border-border bg-card", picked && !pickedHere && "border-ember/60")} aria-label={`${machine.code} crew`}>
      <header className="flex min-w-0 items-baseline justify-between gap-2 border-b border-border px-3 py-2">
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="num shrink-0 font-semibold">{machine.code}</span>
          <span className="label truncate normal-case tracking-[0.04em]">{machine.name}</span>
        </span>
        <span className={cn("label shrink-0", now.length ? "text-foreground" : "")}>
          <span className="num">{now.length}</span> on
        </span>
      </header>

      {now.length > 0 ? (
        <ul className="divide-y divide-border">
          {now.map((c) => {
            const hit = query && matches({ id: c.worker_id, code: c.worker_code, name: c.worker_name }, query);
            return (
              <li key={c.id} className="flex min-w-0 items-center gap-2 py-1 pr-1 pl-3">
                <span className={cn("min-w-0 flex-1 truncate", hit && "text-ember")}>
                  {c.worker_name} <span className="num text-xs text-muted-foreground">{c.worker_code}</span>
                </span>
                <span className="num shrink-0 text-xs text-muted-foreground">since {clock(c.from_at)}</span>
                <Button size="icon-sm" variant="ghost" aria-label={`Take ${c.worker_name} off ${machine.code}`} title="Release" disabled={end.isPending} onClick={() => end.mutate({ id: c.id })}>
                  <UserMinus />
                </Button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-3 py-2.5 text-sm text-muted-foreground">Nobody on this machine.</p>
      )}

      {earlier.length > 0 && (
        <p className="truncate border-t border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground" title={earlier.map((c) => `${c.worker_name} ${clock(c.from_at)}–${clock(c.to_at!)}`).join(", ")}>
          <span className="label mr-1.5">Earlier</span>
          {earlier.map((c) => `${c.worker_name} ${clock(c.from_at)}–${clock(c.to_at!)}`).join(" · ")}
        </p>
      )}

      <div className="border-t border-border p-2">
        {picked && !pickedHere ? (
          <Button className="w-full" size="sm" disabled={assign.isPending} onClick={() => put(picked.worker.id)}>
            <span className="min-w-0 truncate">
              {picked.crew ? "Move" : "Put"} {picked.worker.name} here
            </span>
          </Button>
        ) : (
          <form
            className="flex gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              if (workerId) put(Number(workerId));
            }}
          >
            <Select aria-label={`Worker for ${machine.code}`} value={workerId} onChange={(e) => setWorkerId(e.target.value)} className={cn(compactSelect, "flex-1")}>
              <option value="">Add a worker…</option>
              {groups.map(([label, rows]) =>
                rows.length ? (
                  <optgroup key={label} label={label}>
                    {rows.map((r) => (
                      <option key={r.worker.id} value={r.worker.id}>
                        {r.worker.name} · {r.worker.code}
                        {r.crew ? ` · on ${r.crew.machine_code}` : ""}
                      </option>
                    ))}
                  </optgroup>
                ) : null,
              )}
            </Select>
            <Button type="submit" size="sm" variant="outline" disabled={!workerId || assign.isPending}>
              {roster.find((r) => r.worker.id === Number(workerId))?.crew ? "Move" : "Assign"}
            </Button>
          </form>
        )}
        {error && (
          <p role="alert" className="mt-1.5 text-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}

// the shift before this one; the one before the first shift of a day is last night's
function previousShift(shifts: Shift[], day: string, shiftId: number): { date: string; shift: Shift } | null {
  const ordered = [...shifts].sort((a, b) => a.start_time.localeCompare(b.start_time));
  const i = ordered.findIndex((s) => s.id === shiftId);
  if (i < 0 || ordered.length < 2) return null;
  if (i > 0) return { date: day, shift: ordered[i - 1] };
  const before = new Date(`${day}T00:00:00Z`);
  before.setUTCDate(before.getUTCDate() - 1);
  return { date: before.toISOString().slice(0, 10), shift: ordered[ordered.length - 1] };
}

// shift change in one tap: last shift's crew onto the same machines, absent people skipped
function CarryCrew({ day, shiftId, shifts }: { day: string; shiftId: number; shifts: Shift[] }) {
  const prev = previousShift(shifts, day, shiftId);
  const carry = useFloorAction<object>(() => "/workforce/crew/carry");
  const [done, setDone] = useState<number | null>(null);
  if (!prev) return null;
  const error = Object.values(carry.errors)[0];
  return (
    <div className="grid gap-2">
      <span className="label">Shift change</span>
      <Button
        type="button"
        variant="outline"
        className="h-14"
        disabled={carry.isPending}
        onClick={() =>
          carry.mutate(
            { date: day, shift_id: shiftId, from_date: prev.date, from_shift_id: prev.shift.id },
            { onSuccess: (res) => setDone((res as { created: number }).created) },
          )
        }
      >
        {carry.isPending ? "Bringing crew…" : `Bring crew from ${prev.shift.name}`}
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : (
        done !== null && (
          <p className="label normal-case tracking-[0.04em]">
            <span className="num">{done}</span> placed from {prev.shift.name}
          </p>
        )
      )}
    </div>
  );
}

// R9 + R20: who runs which machine this shift; attendance follows from it
export function CrewBoard() {
  useSSE(["machines"]);
  const current = useCurrentShift();
  const shifts = useShifts();
  const workers = useWorkers();
  const machines = useMachines();

  const [picked, setPicked] = useState<{ date: string; shift: number } | null>(null);
  const day = picked?.date ?? current.data?.date ?? todayIST();
  const shiftId = picked?.shift ?? current.data?.shift_id ?? 0;
  const crew = useCrew(day, shiftId);
  const attendance = useAttendance(day, shiftId);

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [marking, setMarking] = useState<{ worker: Worker; status: AttendanceStatus } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const roster = useMemo(() => rosterOf(workers.data?.items ?? [], crew.data ?? [], attendance.data?.items ?? []), [workers.data, crew.data, attendance.data]);
  const found = query.trim() ? roster.filter((r) => matches(r.worker, query)) : roster;
  const selected = roster.find((r) => r.worker.id === selectedId) ?? null;
  const machineList = machines.data?.items ?? [];
  const stages = [...new Set(machineList.map((m) => m.type))].sort((a, b) => STAGE_ORDER.indexOf(a) - STAGE_ORDER.indexOf(b));

  // "/" jumps to search from anywhere; Esc drops the picked worker
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "/" && !busyTarget(e.target)) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (e.key === "Escape" && !busyTarget(e.target)) {
        setSelectedId(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // pick one worker, show their row and put the cursor on its machine picker
  function open(id: number) {
    setSelectedId(id);
    if (filter !== "all" && found.find((r) => r.worker.id === id)?.status !== filter) setFilter("all");
    requestAnimationFrame(() => {
      document.getElementById(`worker-${id}`)?.scrollIntoView({ block: "nearest" });
      document.getElementById(`assign-${id}`)?.focus();
    });
  }

  // after a placement, clear the slate for the next worker
  function assigned() {
    setSelectedId(null);
    if (query) {
      setQuery("");
      searchRef.current?.focus();
    }
  }

  const queries = [current, shifts, workers, machines, crew, attendance];
  // no shift on right now is fine once one is picked by hand
  const failed = queries.find((q) => q.isError && !(q === current && picked));
  const loading = queries.some((q) => q.isPending && q.fetchStatus !== "idle");
  const visible = filter === "all" ? found : found.filter((r) => r.status === filter);

  return (
    <>
      <PageHeader title="Crew and attendance" description="Put workers on machines at shift start. Attendance fills itself from this." />

      <div className="mb-6 grid items-end gap-4 border border-border bg-card p-4 lg:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
        <div className="grid gap-2">
          <label htmlFor="crew-search" className="label">
            Find a worker
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              ref={searchRef}
              id="crew-search"
              type="text"
              autoComplete="off"
              placeholder="Name or worker code"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSelectedId(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (visible.length === 1) open(visible[0].worker.id);
                  else if (found.length === 1) open(found[0].worker.id);
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  if (query) setQuery("");
                  else e.currentTarget.blur();
                }
              }}
              aria-describedby="crew-search-hint"
              className="h-14 pr-24 pl-11 text-lg"
            />
            <span className="pointer-events-none absolute top-1/2 right-3 flex -translate-y-1/2 items-center gap-2">
              {query && (
                <button type="button" aria-label="Clear search" onClick={() => setQuery("")} className="pointer-events-auto text-muted-foreground hover:text-ember">
                  <X className="size-4" />
                </button>
              )}
              <kbd className="num border border-border px-1.5 py-0.5 text-xs text-muted-foreground">/</kbd>
            </span>
          </div>
          <p id="crew-search-hint" className="label normal-case tracking-[0.04em]">
            {query.trim()
              ? found.length === 1
                ? "1 match · Enter to pick, then choose a machine"
                : `${found.length} matches${found.length ? " · keep typing to narrow" : ""}`
              : `${roster.length} workers · press / to search`}
          </p>
        </div>
        <FormField name="day" label="Date">
          <Input id="day" type="date" max={todayIST()} value={day} onChange={(e) => e.target.value && e.target.checkValidity() && setPicked({ date: e.target.value, shift: shiftId })} className="h-14 w-44" />
        </FormField>
        <FormField name="shift" label="Shift">
          <Select id="shift" value={shiftId} onChange={(e) => setPicked({ date: day, shift: Number(e.target.value) })} className={cn(selectClass, "h-14 w-52")}>
            {shiftId === 0 && (
              <option value={0} disabled>
                Pick a shift
              </option>
            )}
            {(shifts.data?.items ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)})
              </option>
            ))}
          </Select>
        </FormField>
        <CarryCrew key={`${day}-${shiftId}`} day={day} shiftId={shiftId} shifts={shifts.data?.items ?? []} />
      </div>

      {failed ? (
        <EmptyState icon={AlertTriangle} title="Could not load the crew" action={<Button variant="outline" onClick={() => queries.forEach((q) => q.refetch())}>Try again</Button>}>
          {failed.error?.message}
        </EmptyState>
      ) : loading ? (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="grid min-w-0 grid-cols-1 gap-5 lg:scroll-panel lg:max-h-[calc(100dvh-9.5rem)] lg:pr-2" aria-label="Machines">
            {selected && (
              <div className="flex items-center gap-3 border border-ember bg-card px-3 py-2" role="status">
                <span className="min-w-0 flex-1 truncate text-sm">
                  <span className="label mr-2 text-ember">Placing</span>
                  {selected.worker.name} <span className="num text-xs text-muted-foreground">{selected.worker.code}</span>
                  {selected.crew && <span className="text-muted-foreground"> · now on {selected.crew.machine_code}</span>}
                </span>
                <span className="label hidden xl:inline">Esc to cancel</span>
                <Button size="icon-sm" variant="ghost" aria-label="Cancel placing" onClick={() => setSelectedId(null)}>
                  <X />
                </Button>
              </div>
            )}
            {machineList.length === 0 ? (
              <EmptyState icon={Cog} title="No machines">
                Add machines under Masters before planning crew.
              </EmptyState>
            ) : (
              stages.map((stage) => (
                <section key={stage} aria-label={humanize(stage)} className="grid gap-2">
                  <h2 className="eyebrow">
                    {humanize(stage)}
                    <span className="num">{machineList.filter((m) => m.type === stage).length}</span>
                  </h2>
                  <div className="grid gap-2 2xl:grid-cols-2">
                    {machineList
                      .filter((m) => m.type === stage)
                      .map((m) => (
                        <MachineCard
                          key={m.id}
                          machine={m}
                          crew={(crew.data ?? []).filter((c) => c.machine_id === m.id)}
                          roster={roster}
                          day={day}
                          shiftId={shiftId}
                          picked={selected}
                          query={query.trim()}
                          onAssigned={assigned}
                        />
                      ))}
                  </div>
                </section>
              ))
            )}
          </div>

          <div className="grid min-w-0 grid-cols-1 gap-2">
            <AttendancePanel
              rows={found}
              filter={filter}
              onFilter={setFilter}
              searching={!!query.trim()}
              day={day}
              shiftId={shiftId}
              machines={machineList}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onMark={(worker, status) => setMarking({ worker, status })}
              onAssigned={assigned}
            />
          </div>
        </div>
      )}
      <AttendanceDialog
        key={marking ? `${marking.worker.id}-${marking.status}` : "none"}
        worker={marking?.worker ?? null}
        day={day}
        shiftId={shiftId}
        initial={marking?.status}
        current={marking ? roster.find((r) => r.worker.id === marking.worker.id)?.attendance?.status : undefined}
        onClose={() => setMarking(null)}
      />
    </>
  );
}
