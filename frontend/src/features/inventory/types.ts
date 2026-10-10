// shapes returned by /api/inventory (backend/app/modules/inventory/schemas.py)
export type Kg = string; // decimal string, 3 dp, keeps exact grams

export type BatchStatus = "pending_identification" | "inspection" | "approved" | "quarantined" | "rejected";

export type Batch = {
  id: number;
  code: string;
  yarn_item_id: number | null;
  supplier_id: number;
  supplier_lot: string | null;
  receipt_id: number;
  received_kg: Kg;
  unit_cost_paise_per_kg: number;
  status: BatchStatus;
  order_id: number | null;
  mismatch_notes: string | null;
  created_at: string;
  yarn_item: { id: number; fibre: string; count: string; colour: string } | null;
  supplier: { id: number; code: string; name: string } | null;
  receipt: { id: number; code: string; status: string; confirmed_at: string | null } | null;
};

export type StockRow = {
  yarn_item_id: number;
  label: string;
  fibre: string;
  count: string;
  colour: string;
  on_hand_kg: Kg;
  reserved_kg: Kg;
  free_kg: Kg;
  inspection_kg: Kg;
  quarantined_kg: Kg;
  wip_kg: Kg;
  needed_by_orders_kg: Kg;
  projected_free_kg: Kg;
  reorder_level_kg: Kg;
  level: "ok" | "low" | "short";
};

export type Delivery = {
  id: number;
  supplier_id: number;
  supplier_code: string;
  supplier_name: string;
  yarn_item_id: number;
  label: string;
  expected_kg: Kg;
  received_kg: Kg;
  rate_paise_per_kg: number;
  order_id: number | null;
  order_code: string | null;
  expected_date: string;
  status: string;
  created_at: string;
};

export type ComparisonRow = { field: string; expected: string; actual: string; ok: boolean; blocks: boolean };

export type LabelCheck = {
  label: { supplier_code: string; supplier_lot: string; fibre: string; count: string; colour: string; label_kg: Kg };
  supplier: { id: number; code: string; name: string };
  delivery: Delivery | null;
  comparison: ComparisonRow[];
  suggested_rate_paise_per_kg: number | null;
};

export type Receipt = {
  id: number;
  code: string;
  supplier_id: number;
  supplier_name: string;
  expected_delivery: Delivery | null;
  vehicle_no: string | null;
  bill_no: string | null;
  bill_amount_paise: number;
  status: "draft" | "confirmed";
  confirmed_at: string | null;
  created_at: string;
  batches: Batch[];
  total_kg: Kg;
};

export type BatchDetail = {
  batch: Batch;
  where: Record<string, Kg>;
  moves: { id: number; at: string; qty: Kg; from_location: string; to_location: string; reason: string; work_order_code: string | null; source: string }[];
  reservations: { id: number; order_id: number; order_code: string; kg: Kg; status: string }[];
  activity: { at: string; action: string; reason: string | null; data: Record<string, unknown> | null }[];
};

export type PlanLine = {
  yarn_batch_id: number;
  code: string;
  supplier_lot: string | null;
  label: string | null;
  supplier: string;
  received_at: string | null;
  store_kg: Kg;
  reserved_for_order_kg: Kg;
  free_kg: Kg;
  issued_to_work_order_kg: Kg;
};

export type IssuePlan = {
  work_order: { id: number; code: string; stage: string; status: string; order_id: number; order_code: string };
  reserved: PlanLine[];
  free: PlanLine[];
  on_floor: { yarn_batch_id: number; code: string; kg: Kg }[];
};

// walk_in: no request behind it, so the truck needs a rate per kg
export type SampleLabel = { delivery_id: number | null; supplier: string; kg: Kg; kind: "match" | "wrong_colour" | "walk_in"; title: string; payload: string };

export const itemLabel = (i: Batch["yarn_item"]) => (i ? `${i.fibre} ${i.count} ${i.colour}` : "Not identified");

export const qrSrc = (data: string) => `/api/inventory/qr.svg?data=${encodeURIComponent(data)}`;

// a fresh key per user action, so a double tap or scanner repeat posts once
export const newIdemKey = () => `ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
