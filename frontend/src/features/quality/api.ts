"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Paged, qs } from "@/lib/api";

export type Decision = "pass" | "rework" | "reject";
export type RollStatus = "in_process" | "awaiting_qc" | "passed" | "rework" | "rejected" | "dispatched";
export type Stage = "spinning" | "weaving" | "dyeing";

export type Defect = { type: string; count: number; points: number };

export type QueueRow = {
  id: number;
  code: string;
  order_id: number;
  order_code: string;
  buyer_name: string;
  fabric_name: string;
  colour: string;
  loom_code: string;
  shift_code: string;
  weaver_name: string | null;
  length_m: string;
  ready_at: string;
  attempt_no: number;
  deadline: string;
};

export type Check = {
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
  defects: Defect[];
  shade_band: string | null;
  gsm: string | null;
  width_cm: string | null;
  notes: string | null;
  inspector_name: string;
  points: number;
  score: string | null;
};

export type GroupRate = {
  id: number;
  code: string;
  name: string;
  checked: number;
  passed: number;
  rework: number;
  rejected: number;
  defect_rate_pct: string;
  top_defect: string | null;
};

export type Summary = {
  days: number;
  waiting: number;
  waiting_m: string;
  in_rework: number;
  checked: number;
  passed: number;
  rework: number;
  rejected: number;
  passed_m: string;
  rework_m: string;
  rejected_m: string;
  first_pass_yield_pct: string | null;
  by_defect: { type: string; rolls: number; count: number; points: number }[];
  by_loom: GroupRate[];
  by_order: GroupRate[];
};

type Ref = { id: number; code: string; name: string };

export type Trace = {
  roll: {
    id: number;
    code: string;
    status: RollStatus;
    length_m: string;
    shade_band: string | null;
    dye_lot: string | null;
    passed_at: string | null;
    created_at: string;
    location_code: string;
    location_name: string;
  };
  order: { id: number; code: string; status: string; buyer_name: string; colour: string; qty_m: string; deadline: string };
  fabric: { code: string; name: string; width_cm: string; gsm: string; route: Stage[] };
  loom: Ref;
  shift: Ref;
  weaver: Ref | null;
  yarn: { batch_id: number; batch_code: string; kg: string; yarn: string; supplier_code: string; supplier_name: string; supplier_lot: string | null }[];
  checks: Check[];
  events: { at: string; kind: string; machine_code: string | null; work_order_code: string | null; note: string | null }[];
  rework_jobs: { id: number; code: string; stage: Stage; status: string; machine_code: string | null }[];
  dispatch: { id: number; code: string; status: string } | null;
  rework_stages: Stage[];
};

export type InspectBody = {
  decision: Decision;
  defects: { type: string; count: number; points: number }[];
  shade_band?: string;
  gsm?: string;
  width_cm?: string;
  notes?: string;
  rework_stage?: Stage;
  idempotency_key: string;
};

export type InspectResult = { roll_id: number; roll_code: string; status: RollStatus; check: Check; rework_work_order_code: string | null };

// what the inspector sees on the table; hole always scores 4
export const DEFECTS: { type: string; label: string; hint: string }[] = [
  { type: "hole", label: "Hole", hint: "Always 4 points" },
  { type: "colour_mismatch", label: "Colour mismatch", hint: "Shade off the approved standard" },
  { type: "uneven_weave", label: "Uneven weave", hint: "Thick or thin places, bars" },
  { type: "broken_end", label: "Broken end", hint: "Missing warp thread" },
  { type: "broken_pick", label: "Broken pick", hint: "Missing weft thread" },
  { type: "stain", label: "Stain", hint: "Oil, rust or dirt" },
  { type: "selvedge", label: "Selvedge fault", hint: "Torn, loose or curled edge" },
  { type: "other", label: "Other", hint: "Describe it in the notes" },
];
export const defectLabel = (type: string) => DEFECTS.find((d) => d.type === type)?.label ?? type.replaceAll("_", " ");

// 4-point system: points per fault by its length
export const SIZES = [
  { points: 1, label: "Up to 7.5 cm" },
  { points: 2, label: "7.5 to 15 cm" },
  { points: 3, label: "15 to 23 cm" },
  { points: 4, label: "Over 23 cm" },
];

export const DECISION_LABEL: Record<Decision, string> = { pass: "Pass", rework: "Rework", reject: "Reject" };

// points per 100 m² of cloth, same rule as the server
export function scorePer100(points: number, lengthM: number, widthCm: number) {
  const area = (lengthM * widthCm) / 100;
  return area > 0 ? Math.round((points * 100 * 10) / area) / 10 : null;
}

// query keys start with "quality" so the SSE topic refreshes them
export const useQcSummary = (days: number) =>
  useQuery({ queryKey: ["quality", "summary", days], queryFn: () => api<Summary>(`/quality/summary?days=${days}`), placeholderData: keepPreviousData });

export const useQueue = () =>
  useQuery({ queryKey: ["quality", "queue"], queryFn: () => api<Paged<QueueRow>>("/quality/queue?limit=200") });

export type CheckFilters = { decision?: string; machine_id?: number; order_id?: number };

export const useChecks = (filters: CheckFilters, offset: number, limit: number) =>
  useQuery({
    queryKey: ["quality", "checks", filters, offset, limit],
    queryFn: () => api<Paged<Check>>(`/quality/checks${qs({ ...filters, offset, limit })}`),
    placeholderData: keepPreviousData,
  });

export const useTrace = (id: number) => useQuery({ queryKey: ["quality", "roll", id], queryFn: () => api<Trace>(`/quality/rolls/${id}`) });

export const findRoll = (code: string) => api<Paged<{ id: number; code: string }>>(`/quality/rolls${qs({ code, limit: 1 })}`);

export function useInspect(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InspectBody) => api<InspectResult>(`/quality/rolls/${id}/inspect`, { method: "POST", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quality"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["machines"] });
    },
  });
}
