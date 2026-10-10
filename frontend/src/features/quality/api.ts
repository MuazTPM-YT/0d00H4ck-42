"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type Paged } from "@/lib/api";

export type Decision = "pass" | "rework" | "reject";
export type DefectType = "hole" | "colour_mismatch" | "uneven_weave" | "other";
export type ShadeBand = "A" | "B" | "C";

export const DEFECT_TYPES: DefectType[] = ["hole", "colour_mismatch", "uneven_weave", "other"];
export const SHADE_BANDS: ShadeBand[] = ["A", "B", "C"];

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
  defects: { type: DefectType; count: number }[];
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
  defects: { type: DefectType; count: number }[];
  shade_band: ShadeBand | null;
  gsm: string | null;
  width_cm: string | null;
  note: string | null;
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

// one decision per inspection; field errors land next to the field
export function useDecide(rollId: number) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: (body: CheckBody) => api<{ roll: { code: string; status: string } }>(`/quality/rolls/${rollId}/checks`, { method: "POST", json: body }),
    onMutate: () => setErrors({}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quality"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });
  return { ...mutation, errors };
}
