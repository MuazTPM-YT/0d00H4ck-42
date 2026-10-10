"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, ApiError, type Paged } from "@/lib/api";

export type Stage = "spinning" | "weaving" | "dyeing";
export type MachineStatus = "running" | "idle" | "breakdown" | "maintenance" | "off";
export type WorkOrderStatus = "waiting" | "queued" | "running" | "paused" | "done";
export type Unit = "kg" | "m";

export const MACHINE_STATUSES: MachineStatus[] = ["running", "idle", "breakdown", "maintenance", "off"];
export const DOWNTIME: MachineStatus[] = ["breakdown", "maintenance"];

export type BoardTile = {
  machine_id: number;
  code: string;
  name: string;
  type: Stage;
  unit: Unit;
  status: MachineStatus;
  since: string | null;
  reason: string | null;
  // who reported the latest status: a machine feed or a person
  source: "manual" | "scanner" | "machine" | null;
  job: {
    work_order_id: number;
    code: string;
    order_id: number;
    order_code: string;
    stage: Stage;
    status: WorkOrderStatus;
    planned: string;
    produced: string;
    unit: Unit;
    roll_id: number | null;
  } | null;
  today_output: string;
  queued: number;
  crew: string[];
};

export type Board = { as_of: string; shift_code: string | null; machines: BoardTile[] };

export type MachineEvent = { id: number; at: string; status: MachineStatus; reason: string | null; work_order_id: number | null; source: string };
export type OutputLog = { id: number; work_order_id: number; at: string; qty: string; unit: Unit; source: string; worker_id: number | null };
export type Timeline = {
  machine_id: number;
  code: string;
  date: string;
  unit: Unit;
  events: MachineEvent[];
  seconds: Partial<Record<MachineStatus, number>>;
  output: OutputLog[];
  total_output: string;
};

export type OpenWorkOrder = {
  id: number;
  code: string;
  order_id: number;
  order_code: string;
  deadline: string;
  stage: Stage;
  seq: number;
  machine_id: number | null;
  planned_qty: string;
  produced: string;
  unit: Unit;
  status: WorkOrderStatus;
  queue_position: number | null;
  roll_id: number | null;
};

export type Machine = { id: number; code: string; name: string; type: Stage; output_unit: Unit; active: boolean };
export type Roll = { id: number; code: string; length_m: string; status: string; order_id: number };

// query keys start with "machines" so the SSE topic refreshes them
export const useBoard = () => useQuery({ queryKey: ["machines", "board"], queryFn: () => api<Board>("/production/board") });

export const useTimeline = (machineId: number | null, date: string) =>
  useQuery({
    queryKey: ["machines", "timeline", machineId, date],
    queryFn: () => api<Timeline>(`/production/machines/${machineId}/timeline?date=${date}`),
    enabled: machineId !== null,
  });

export const useOpenWorkOrders = () =>
  useQuery({ queryKey: ["machines", "work-orders", "open"], queryFn: () => api<OpenWorkOrder[]>("/production/work-orders/open") });

export const useMachines = () =>
  useQuery({
    queryKey: ["machines", "list"],
    queryFn: () => api<Paged<Machine>>("/masters/machines?active=true&limit=200"),
    staleTime: 300_000,
  });

// rolls woven for this order and waiting for the next stage
export const useRollsToProcess = (orderId: number | null) =>
  useQuery({
    queryKey: ["quality", "rolls", "in_process", orderId],
    queryFn: () => api<Paged<Roll>>(`/quality/rolls?status=in_process&order_id=${orderId}&limit=200`),
    enabled: orderId !== null,
  });

// one mutation shape for every floor action; field errors land next to the field
export function useFloorAction<Body>(path: (body: Body) => string, method: "POST" | "PUT" = "POST") {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: (body: Body) => api(path(body), { method, json: body }),
    onMutate: () => setErrors({}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["machines"] });
      qc.invalidateQueries({ queryKey: ["quality"] });
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });
  return { ...mutation, errors };
}

// re-render every 30 s so "time in status" keeps moving between server updates
export function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

// "2 h 05 m", "12 m", "just now"
export function duration(seconds: number) {
  if (seconds < 60) return "just now";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, "0")} m` : `${m} m`;
}

// today's date in the mill's time zone, as YYYY-MM-DD
export const todayIST = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export const pct = (done: string | number, planned: string | number) =>
  Math.min(100, Math.round((Number(done) / Math.max(Number(planned), 0.001)) * 100));
