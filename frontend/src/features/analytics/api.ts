"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Paged, qs } from "@/lib/api";

export type Severity = "info" | "warn" | "critical";
export type InsightStatus = "open" | "acknowledged" | "resolved";
export type Risk = "on_track" | "at_risk" | "late";

export type RecordRef = { type: string; id: number; code: string };

export type Insight = {
  id: number;
  kind: string;
  severity: Severity;
  entity_type: string;
  entity_id: number;
  title: string;
  facts: Record<string, unknown> & { records?: RecordRef[] };
  narrative: string | null;
  status: InsightStatus;
  created_at: string;
};

export type AttentionItem = {
  kind: string;
  severity: Severity;
  title: string;
  detail: string | null;
  href: string;
  entity_type: string;
  entity_id: number;
  since: string | null;
};

export type Briefing = { role: string; text: string; items: number };

export type PlannedStage = {
  work_order_id: number;
  code: string;
  stage: string;
  remaining: number;
  unit: "kg" | "m";
  machine: string | null;
  start: string | null;
  end: string | null;
};

export type DeliveryEstimate = {
  order_id: number;
  order_code: string;
  deadline: string;
  expected_at: string | null;
  status: Risk;
  slack_hours: number | null;
  blocked_by: string[];
  stages: PlannedStage[];
  basis: {
    throughputs: Record<string, { per_hour: number; from: string }>;
    qc_hours: number;
    dispatch_hours: number;
    repair_hours: number;
    rule: string;
  };
};

export const KIND_LABEL: Record<string, string> = {
  supplier_defects: "Supplier quality",
  defect_root_cause: "Defect root cause",
  machine_slowdown: "Machine slowdown",
  breakdown_cluster: "Repeated breakdowns",
  shift_change_idle: "Handover idle",
  yarn_yield_gap: "Yarn yield",
  impossible_data: "Impossible data",
};

// where each record behind a finding lives in the app
const RECORD_PAGE: Record<string, (id: number) => string> = {
  rolls: (id) => `/qc/rolls/${id}`,
  orders: (id) => `/orders/${id}`,
  machines: () => "/floor",
  machine_events: () => "/floor",
  production_logs: () => "/floor",
  work_orders: () => "/floor/work-orders",
  yarn_batches: () => "/store/batches",
  suppliers: () => "/masters/suppliers",
};
export const recordHref = (r: RecordRef) => RECORD_PAGE[r.type]?.(r.id) ?? null;

// keys start with their SSE topic: "insights" refetch on new findings, "orders" on forecast moves
export type InsightFilters = { status: string; severity: string; kind: string };

export const useInsights = (filters: InsightFilters, offset: number, limit: number) =>
  useQuery({
    queryKey: ["insights", "list", filters, offset, limit],
    queryFn: () => api<Paged<Insight>>(`/analytics/insights${qs({ ...filters, offset, limit })}`),
  });

export const useInsight = (id: number | null) =>
  useQuery({
    queryKey: ["insights", "one", id],
    queryFn: () => api<Insight>(`/analytics/insights/${id}`),
    enabled: id !== null,
  });

// attention mixes floor, QC, orders and money: refetch every minute as well as on insights
export const useAttention = () =>
  useQuery({ queryKey: ["insights", "attention"], queryFn: () => api<AttentionItem[]>("/analytics/attention"), refetchInterval: 60_000 });

export const useBriefing = () =>
  useQuery({ queryKey: ["insights", "briefing"], queryFn: () => api<Briefing>("/analytics/briefing"), refetchInterval: 60_000 });

export const useDeliveryBoard = () =>
  useQuery({ queryKey: ["orders", "delivery"], queryFn: () => api<DeliveryEstimate[]>("/analytics/delivery") });

export const useDeliveryEstimate = (orderId: number) =>
  useQuery({
    queryKey: ["orders", "delivery", orderId],
    queryFn: () => api<DeliveryEstimate>(`/analytics/orders/${orderId}/delivery-estimate`),
    retry: false,
  });

export function useInsightAction(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ action, note }: { action: "acknowledge" | "resolve"; note: string }) =>
      api<Insight>(`/analytics/insights/${id}/${action}`, { method: "POST", json: { note } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insights"] }),
  });
}

export function useRunDetectors() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ created: number; updated: number; unchanged: number; skipped: number }>("/analytics/run", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insights"] }),
  });
}
