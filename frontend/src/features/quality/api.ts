"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type Paged, qs } from "@/lib/api";

export type Decision = "pass" | "rework" | "reject";
export type DefectType = "hole" | "colour_mismatch" | "uneven_weave" | "broken_end" | "broken_pick" | "stain" | "selvedge" | "other";
export type ShadeBand = "A" | "B" | "C";
export type Stage = "spinning" | "weaving" | "dyeing";

// what the inspector sees on the table, in the order faults are usually found
export const DEFECTS: { type: DefectType; label: string; hint: string }[] = [
  { type: "hole", label: "Hole", hint: "Always 4 points" },
  { type: "colour_mismatch", label: "Colour mismatch", hint: "Shade off the approved standard" },
  { type: "uneven_weave", label: "Uneven weave", hint: "Thick or thin places, bars" },
  { type: "broken_end", label: "Broken end", hint: "Missing warp thread" },
  { type: "broken_pick", label: "Broken pick", hint: "Missing weft thread" },
  { type: "stain", label: "Stain", hint: "Oil, rust or dirt" },
  { type: "selvedge", label: "Selvedge fault", hint: "Torn, loose or curled edge" },
  { type: "other", label: "Other", hint: "Say what in the note" },
];
export const DEFECT_TYPES: DefectType[] = DEFECTS.map((d) => d.type);
export const defectLabel = (type: string) => DEFECTS.find((d) => d.type === type)?.label ?? type.replaceAll("_", " ");
export const SHADE_BANDS: ShadeBand[] = ["A", "B", "C"];

// 4-point system: a fault scores by its length; a hole always scores 4
export const SIZES = [
  { points: 1, label: "Up to 7.5 cm" },
  { points: 2, label: "7.5 to 15 cm" },
  { points: 3, label: "15 to 23 cm" },
  { points: 4, label: "Over 23 cm" },
];
export const defectPoints = (defects: { type: string; count: number; points?: number }[]) =>
  defects.reduce((s, d) => s + d.count * (d.points ?? (d.type === "hole" ? 4 : 1)), 0);

// points per 100 m² of cloth, same rule as the server
export function scorePer100(points: number, lengthM: number, widthCm: number) {
  const area = (lengthM * widthCm) / 100;
  return area > 0 ? Math.round((points * 1000) / area) / 10 : null;
}

export type RollRow = {
  id: number;
  code: string;
  status: string;
  length_m: string;
  shade_band: string | null;
  order_id: number;
  order_code: string;
  buyer_name: string;
  fabric_name: string;
  fabric_gsm: string;
  fabric_width_cm: string;
  colour: string;
  loom_code: string;
  shift_name: string;
  weaver_name: string | null;
  created_at: string;
  waiting_since: string;
};

export type QcCheck = {
  id: number;
  at: string;
  attempt_no: number;
  decision: Decision;
  defects: { type: DefectType; count: number; points?: number }[];
  shade_band: string | null;
  gsm: string | null;
  width_cm: string | null;
  notes: string | null;
};

export type RollDetail = RollRow & { checks: QcCheck[] };

export type DecisionCounts = { passed: number; rework: number; rejected: number };
export type DefectGroup = { key: string; checks: number; defects: number };
export type QualitySummary = {
  days: number;
  waiting: number;
  first_attempt: DecisionCounts;
  all_attempts: DecisionCounts;
  pass_rate_pct: number | null;
  defects_by_type: Partial<Record<DefectType, number>>;
  by_machine: DefectGroup[];
  by_order: DefectGroup[];
};

export type CheckBody = {
  decision: Decision;
  defects: { type: DefectType; count: number; points: number }[];
  shade_band: ShadeBand | null;
  gsm: string | null;
  width_cm: string | null;
  note: string | null;
  rework_stage: Stage | null;
  idempotency_key: string;
};

// one check with names and score, for the checks list
export type CheckRow = {
  id: number;
  roll_id: number;
  roll_code: string;
  order_id: number;
  order_code: string;
  loom_code: string;
  length_m: string;
  at: string;
  attempt_no: number;
  decision: Decision;
  defects: { type: string; count: number; points: number }[];
  shade_band: string | null;
  gsm: string | null;
  width_cm: string | null;
  notes: string | null;
  inspector_name: string;
  points: number;
  score: string | null;
};

type Ref = { id: number; code: string; name: string };

// where a roll came from: yarn lots, every event, rework jobs, the truck it left on
export type Trace = {
  roll: { id: number; code: string; status: string; location_code: string; location_name: string };
  fabric: { route: Stage[] };
  loom: Ref;
  weaver: Ref | null;
  yarn: { batch_id: number; batch_code: string; kg: string; yarn: string; supplier_code: string; supplier_name: string; supplier_lot: string | null }[];
  events: { at: string; kind: string; machine_code: string | null; work_order_code: string | null; note: string | null }[];
  rework_jobs: { id: number; code: string; stage: Stage; status: string; machine_code: string | null }[];
  dispatch: { id: number; code: string; status: string } | null;
  rework_stages: Stage[];
};

// query keys start with "quality" so the SSE topic refreshes them
export const useQueue = (offset: number, limit: number) =>
  useQuery({
    queryKey: ["quality", "queue", offset, limit],
    queryFn: () => api<Paged<RollRow>>(`/quality/queue?offset=${offset}&limit=${limit}`),
  });

export const useSummary = (days = 30) =>
  useQuery({ queryKey: ["quality", "summary", days], queryFn: () => api<QualitySummary>(`/quality/summary?days=${days}`) });

export const useRoll = (id: number | null) =>
  useQuery({
    queryKey: ["quality", "roll", id],
    queryFn: () => api<RollDetail>(`/quality/rolls/${id}`),
    enabled: id !== null,
  });

export const useTrace = (id: number | null) =>
  useQuery({ queryKey: ["quality", "trace", id], queryFn: () => api<Trace>(`/quality/rolls/${id}/trace`), enabled: id !== null });

export type CheckFilters = { decision?: string; machine_id?: number; order_id?: number };

export const useChecks = (filters: CheckFilters, offset: number, limit: number) =>
  useQuery({
    queryKey: ["quality", "checks", filters, offset, limit],
    queryFn: () => api<Paged<CheckRow>>(`/quality/checks${qs({ ...filters, offset, limit })}`),
    placeholderData: keepPreviousData,
  });

// a scanner types the code and Enter: exact match on the roll code
export const findRoll = (code: string) => api<Paged<{ id: number }>>(`/quality/rolls${qs({ code, limit: 1 })}`);

// one decision per inspection; field errors land next to the field
export function useDecide(rollId: number) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: (body: CheckBody) => api<{ roll: { id: number; code: string; status: string }; rework_work_order_id: number | null; dispatch_code: string | null }>(`/quality/rolls/${rollId}/checks`, { method: "POST", json: body }),
    onMutate: () => setErrors({}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quality"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["machines"] });
      qc.invalidateQueries({ queryKey: ["dispatch"] });
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });
  return { ...mutation, errors };
}
