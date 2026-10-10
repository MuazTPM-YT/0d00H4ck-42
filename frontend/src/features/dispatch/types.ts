// shapes returned by /api/dispatch (backend/app/modules/dispatch/schemas.py)
export type DispatchStatus = "draft" | "loading" | "confirmed";

export type DispatchRow = {
  id: number;
  code: string;
  order_id: number;
  buyer_id: number;
  vehicle_no: string | null;
  driver: string | null;
  status: DispatchStatus;
  confirmed_at: string | null;
  created_at: string;
  delivered_at: string | null;
  order_code: string;
  buyer_name: string;
  roll_count: number;
  metres: string;
  invoice_id: number | null;
  invoice_code: string | null;
};

export type LoadedRoll = { id: number; code: string; length_m: string; shade_band: string | null; location: string };

export type Proposal = {
  band: string | null;
  roll_ids: number[];
  total_m: string;
  need_m: string;
  overshoot_m: string;
  short_m: string;
};

export type DispatchDetail = Omit<DispatchRow, "roll_count" | "metres"> & {
  buyer_gstin: string;
  buyer_city: string | null;
  fabric: string;
  colour: string;
  ordered_m: string;
  shipped_m: string;
  remaining_m: string;
  loaded: LoadedRoll[];
  loaded_m: string;
  bands: string[];
  shade_override: string | null;
  proposal: Proposal | null;
  candidates: LoadedRoll[];
  // driver link key once the truck left; the code itself only ever shows on the buyer link
  delivery_token: string | null;
  received_by: string | null;
  delivery_note: string | null;
  has_code: boolean;
  tries_left: number;
};

// a confirmed truck is on the road until the buyer's code closes the trip
export function tripStatus(d: { status: string; delivered_at: string | null }): string {
  if (d.delivered_at) return "delivered";
  return d.status === "confirmed" ? "on_the_way" : d.status;
}

export type ScanResult = {
  dispatch_id: number;
  status: DispatchStatus;
  roll_code: string;
  roll_count: number;
  loaded_m: string;
  remaining_m: string;
  bands: string[];
};

export type ShelfRoll = LoadedRoll & { order_id: number; days_on_shelf: number; dispatch_code: string | null };

export type ShelfGroup = {
  order_id: number;
  order_code: string;
  buyer_name: string;
  order_open: boolean;
  ordered_m: string;
  shipped_m: string;
  on_shelf_m: string;
  rolls: ShelfRoll[];
};

export type CornerItem = {
  roll_id: number;
  roll_code: string;
  order_code: string;
  length_m: string;
  days_on_shelf: number;
  reasons: string[];
};
