"use client";

import { useQuery } from "@tanstack/react-query";

import { api, apiAll } from "@/lib/api";

export type Shift = { id: number; code: string; name: string; start_time: string; end_time: string };
export type Worker = { id: number; code: string; name: string };
export type Crew = {
  id: number;
  worker_id: number;
  worker_code: string;
  worker_name: string;
  machine_id: number;
  machine_code: string;
  from_at: string;
  to_at: string | null;
};
export type AttendanceStatus = "present" | "absent" | "half_day";
export type Attendance = { id: number; worker_id: number; status: AttendanceStatus; source: "crew" | "manual" };

// where a worker stands this shift; on a machine beats whatever attendance says
export type RosterStatus = "on_machine" | "free" | "absent" | "unmarked";
export type RosterRow = { worker: Worker; status: RosterStatus; crew?: Crew; attendance?: Attendance };

export const ATTENDANCE: AttendanceStatus[] = ["present", "half_day", "absent"];

// query keys start with "machines" so the SSE topic and floor actions refresh them
export const useCurrentShift = () =>
  useQuery({ queryKey: ["machines", "current-shift"], queryFn: () => api<{ date: string; shift_id: number }>("/workforce/current-shift") });

export const useShifts = () =>
  useQuery({ queryKey: ["masters", "shifts", "all"], queryFn: () => apiAll<Shift>("/masters/shifts") });

export const useWorkers = () =>
  useQuery({ queryKey: ["masters", "workers", "active"], queryFn: () => apiAll<Worker>("/masters/workers?active=true") });

export const useCrew = (day: string, shiftId: number) =>
  useQuery({
    queryKey: ["machines", "crew", day, shiftId],
    queryFn: () => api<Crew[]>(`/workforce/crew?date=${day}&shift_id=${shiftId}`),
    enabled: shiftId > 0,
  });

export const useAttendance = (day: string, shiftId: number) =>
  useQuery({
    queryKey: ["machines", "attendance", day, shiftId],
    queryFn: () => apiAll<Attendance>(`/workforce/attendance?date=${day}&shift_id=${shiftId}`),
    enabled: shiftId > 0,
  });

export function rosterOf(workers: Worker[], crew: Crew[], attendance: Attendance[]): RosterRow[] {
  const onMachine = new Map(crew.filter((c) => !c.to_at || Date.parse(c.to_at) > Date.now()).map((c) => [c.worker_id, c]));
  const marked = new Map(attendance.map((a) => [a.worker_id, a]));
  return workers.map((worker) => {
    const c = onMachine.get(worker.id);
    const a = marked.get(worker.id);
    const status: RosterStatus = c ? "on_machine" : !a ? "unmarked" : a.status === "absent" ? "absent" : "free";
    return { worker, status, crew: c, attendance: a };
  });
}

// name or code, any order of words: "ravi w-0" finds Ravi Kumar, W-014
export function matches(worker: Worker, query: string) {
  const hay = `${worker.name} ${worker.code}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word));
}

export const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" });
