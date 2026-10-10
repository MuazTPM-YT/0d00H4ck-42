// shapes returned by /api/orders (backend/app/modules/orders/schemas.py)
export type Order = {
  id: number;
  code: string;
  buyer_id: number;
  fabric_type_id: number;
  colour: string;
  qty_m: string;
  rate_paise_per_m: number;
  deadline: string;
  status: "draft" | "confirmed" | "cancelled" | "closed";
  confirmed_at: string | null;
  created_at: string;
  buyer: { id: number; code: string; name: string } | null;
  fabric_type: { id: number; code: string; name: string } | null;
};

export type YarnLine = { fibre: string; count: string; colour: string; kg_needed: string; kg_free: string; kg_short: string };

export type AllocationLine = YarnLine & {
  yarn_item_id: number | null;
  kg_reserved: string;
  kg_issued: string;
  lots: { yarn_batch_id: number; code: string; supplier_lot: string | null; supplier: string; reserved_kg: string; consumed_kg: string }[];
  mixed_lots: boolean;
};

export type Allocation = { order_id: number; code: string; status: Order["status"]; lines: AllocationLine[]; mixed_lots: boolean; fully_covered: boolean };

export type ToBuyRow = {
  order_id: number;
  order_code: string;
  buyer: string;
  deadline: string;
  yarn_item_id: number | null;
  label: string;
  short_kg: string;
  free_cover_kg: string;
  on_order_kg: string;
  to_buy_kg: string;
  suggested_supplier_id: number | null;
  suggested_rate_paise_per_kg: number | null;
};
