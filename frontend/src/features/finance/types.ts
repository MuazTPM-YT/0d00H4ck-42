// shapes returned by /api/finance (backend/app/modules/finance/schemas.py)
export type InvoiceStatus = "issued" | "part_paid" | "paid";

export type InvoiceRow = {
  id: number;
  code: string;
  dispatch_id: number;
  order_id: number;
  subtotal_paise: number;
  tax_paise: number;
  total_paise: number;
  issued_at: string;
  due_date: string;
  status: InvoiceStatus;
  buyer_name: string;
  order_code: string;
  dispatch_code: string;
  paid_paise: number;
  outstanding_paise: number;
  days_overdue: number;
};

export type Payment = { id: number; invoice_id: number; amount_paise: number; received_at: string; mode: string; ref: string | null };

export type InvoiceDetail = InvoiceRow & {
  buyer_gstin: string;
  buyer_city: string | null;
  fabric: string;
  colour: string;
  vehicle_no: string | null;
  gst_pct: string;
  lines: { roll_code: string; shade_band: string | null; metres: string; rate_paise_per_m: number; amount_paise: number }[];
  payments: Payment[];
};

export type PaymentRow = Payment & { invoice_code: string; buyer_name: string };

export type WageRun = { id: number; period_start: string; period_end: string; status: "draft" | "final" | "paid"; workers: number; total_paise: number; created_at: string };

export type WageRunDetail = WageRun & {
  lines: { worker_id: number; worker_code: string; worker_name: string; wage_type: string; rate_paise: number; days: string; metres: string; amount_paise: number }[];
};

export type CostLine = { label: string; detail: string; amount_paise: number };

export type OrderCost = {
  order_code: string;
  yarn_paise: number;
  machine_paise: number;
  labour_paise: number;
  total_paise: number;
  yarn: CostLine[];
  machine: CostLine[];
  labour: CostLine[];
  produced_m: string;
  passed_m: string;
  rejected_m: string;
  passed_rolls: number;
  reject_share_paise: number;
  cost_per_m_paise: number | null;
  cost_per_roll_paise: number | null;
  cost_provisional: boolean; // QC or work not finished: per-metre cost can still move
  cost_to_date: boolean; // a job is still running
  invoiced_paise: number;
  invoiced_m: string;
  margin_paise: number | null;
  rules: string[];
};

export type MonthView = {
  month: string;
  invoiced_paise: number;
  invoiced_ex_gst_paise: number;
  received_paise: number;
  yarn_bills_paise: number;
  wages_accrued_paise: number;
  wages_paid_paise: number;
  expenses_paise: number;
  result_invoiced_paise: number;
  result_cash_paise: number;
  notes: string[];
};

export type MonthKind = "invoiced" | "received" | "yarn_bills" | "wages" | "wages_paid" | "expenses";
export type MonthRecord = { on: string; ref: string; party: string; amount_paise: number; link: string | null };

export type MachineProduction = {
  machine_id: number;
  code: string;
  name: string;
  unit: "kg" | "m";
  month_qty: string;
  days: { day: string; qty: string }[];
  hours: Record<"running" | "idle" | "breakdown" | "maintenance" | "off", string>;
};

export const PAYMENT_MODES = ["bank_transfer", "upi", "cheque", "cash"] as const;
export const SELECT = "h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm";
