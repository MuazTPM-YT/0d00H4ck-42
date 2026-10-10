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
};

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
  free_m: string; // passed, on no truck
  on_truck_m: string; // passed, loaded on an open truck
  rolls: ShelfRoll[];
};

// a roll forgotten on the shelf, or a truck left open
export type CornerItem = {
  kind: "roll" | "dispatch";
  roll_id: number | null;
  roll_code: string | null;
  dispatch_id: number | null;
  dispatch_code: string | null;
  order_code: string;
  length_m: string;
  days_on_shelf: number;
  reasons: string[];
};
