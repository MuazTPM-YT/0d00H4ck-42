import type { ReactNode } from "react";

import { StatusBadge } from "@/components/layout/StatusBadge";
import { inr, kg } from "@/lib/format";

export type Row = { id: number; [key: string]: unknown };

export type Field = {
  name: string;
  label: string;
  kind: "text" | "email" | "number" | "money" | "select" | "time" | "bool";
  required?: boolean;
  options?: { value: string; label: string }[];
  pattern?: string;
  maxLength?: number;
  step?: string;
  min?: number;
  max?: number;
  hint?: string;
  showWhen?: (values: Record<string, string | boolean>) => boolean;
};

export type Master = {
  path: string; // API path and URL segment
  title: string;
  singular: string;
  description: string;
  fields: Field[];
  columns: { key: string; header: string; cell: (row: Row) => ReactNode; className?: string }[];
  hasActive: boolean;
  // values the server needs but the user should not have to pick
  derive?: (values: Record<string, string | boolean>) => Record<string, unknown>;
};

const CODE = { pattern: "[A-Za-z0-9][A-Za-z0-9\\-]{0,19}", maxLength: 20, hint: "Letters, digits and dashes. Saved in capitals." };
const GSTIN = { pattern: "\\d{2}[A-Za-z]{5}\\d{4}[A-Za-z][1-9A-Za-z][Zz][0-9A-Za-z]", maxLength: 15, hint: "15 characters, e.g. 29AAGFG9753P1Z4" };
const PHONE = { pattern: "\\+?[0-9][0-9 \\-]{6,18}", maxLength: 20 };
const STAGES = [
  { value: "spinning", label: "Spinning" },
  { value: "weaving", label: "Weaving" },
  { value: "dyeing", label: "Dyeing" },
];

const text = (key: string, header: string, className?: string) => ({
  key, header, className, cell: (r: Row) => (r[key] as string | null) ?? "—",
});
const active = { key: "active", header: "Status", cell: (r: Row) => <StatusBadge status={r.active ? "active" : "off"} /> };

export const MASTERS: Master[] = [
  {
    path: "suppliers", title: "Suppliers", singular: "supplier", hasActive: true,
    description: "Yarn suppliers. Their lot numbers are matched at the gate.",
    fields: [
      { name: "code", label: "Code", kind: "text", required: true, ...CODE },
      { name: "name", label: "Name", kind: "text", required: true, maxLength: 120 },
      { name: "gstin", label: "GSTIN", kind: "text", ...GSTIN },
      { name: "phone", label: "Phone", kind: "text", ...PHONE },
      { name: "city", label: "City", kind: "text", maxLength: 120 },
      { name: "active", label: "Active", kind: "bool" },
    ],
    columns: [text("code", "Code", "font-medium"), text("name", "Name"), text("city", "City"), text("gstin", "GSTIN"), active],
  },
  {
    path: "buyers", title: "Buyers", singular: "buyer", hasActive: true,
    description: "Customers who place fabric orders. GSTIN goes on every invoice.",
    fields: [
      { name: "code", label: "Code", kind: "text", required: true, ...CODE },
      { name: "name", label: "Name", kind: "text", required: true, maxLength: 120 },
      { name: "gstin", label: "GSTIN", kind: "text", required: true, ...GSTIN },
      { name: "contact_name", label: "Contact person", kind: "text", maxLength: 120 },
      { name: "phone", label: "Phone", kind: "text", ...PHONE },
      { name: "email", label: "Email", kind: "email", maxLength: 254 },
      { name: "city", label: "City", kind: "text", maxLength: 120 },
      { name: "active", label: "Active", kind: "bool" },
    ],
    columns: [text("code", "Code", "font-medium"), text("name", "Name"), text("city", "City"), text("gstin", "GSTIN"), active],
  },
  {
    path: "yarn-items", title: "Yarn items", singular: "yarn item", hasActive: true,
    description: "Each fibre, count and colour the mill stocks, with its reorder level.",
    fields: [
      { name: "fibre", label: "Fibre or blend", kind: "text", required: true, maxLength: 40, hint: "e.g. Cotton, Poly-cotton 65/35" },
      { name: "count", label: "Count", kind: "text", required: true, maxLength: 20, hint: "e.g. Ne 30/1" },
      { name: "colour", label: "Colour", kind: "text", required: true, maxLength: 40, hint: "Use Raw White for undyed yarn" },
      { name: "reorder_level_kg", label: "Reorder level (kg)", kind: "number", min: 0, max: 999999999.999, step: "0.001", required: true },
      { name: "active", label: "Active", kind: "bool" },
    ],
    columns: [
      text("fibre", "Fibre", "font-medium"), text("count", "Count"), text("colour", "Colour"),
      { key: "reorder_level_kg", header: "Reorder level", className: "text-right", cell: (r) => kg(r.reorder_level_kg as string) },
      active,
    ],
  },
  {
    path: "machines", title: "Machines", singular: "machine", hasActive: true,
    description: "Spinning frames, looms and dyeing machines, with running cost per hour.",
    fields: [
      { name: "code", label: "Code", kind: "text", required: true, ...CODE },
      { name: "name", label: "Name", kind: "text", required: true, maxLength: 120 },
      { name: "type", label: "Type", kind: "select", required: true, options: STAGES, hint: "Spinning reports kg; weaving and dyeing report metres." },
      { name: "rated_output_per_hour", label: "Rated output per hour", kind: "number", min: 0.001, max: 999999999.999, step: "0.001", required: true },
      { name: "hourly_cost_paise", label: "Running cost per hour (₹)", kind: "money", min: 0, max: 1000000000000, required: true },
      { name: "active", label: "Active", kind: "bool" },
    ],
    derive: (v) => ({ output_unit: v.type === "spinning" ? "kg" : "m" }),
    columns: [
      text("code", "Code", "font-medium"), text("name", "Name"),
      { key: "type", header: "Type", cell: (r) => <span className="capitalize">{r.type as string}</span> },
      { key: "rated", header: "Rated output", className: "text-right", cell: (r) => `${Number(r.rated_output_per_hour)} ${r.output_unit}/h` },
      { key: "cost", header: "Cost per hour", className: "text-right", cell: (r) => inr(r.hourly_cost_paise as number) },
      active,
    ],
  },
  {
    path: "workers", title: "Workers", singular: "worker", hasActive: true,
    description: "Floor staff. Daily-wage or paid per metre woven.",
    fields: [
      { name: "code", label: "Code", kind: "text", required: true, ...CODE },
      { name: "name", label: "Name", kind: "text", required: true, maxLength: 120 },
      { name: "wage_type", label: "Wage type", kind: "select", required: true, options: [{ value: "daily", label: "Daily wage" }, { value: "piece", label: "Per metre" }] },
      { name: "daily_rate_paise", label: "Daily rate (₹)", kind: "money", min: 0.01, max: 1000000, required: true, showWhen: (v) => v.wage_type === "daily" },
      { name: "piece_rate_paise_per_m", label: "Rate per metre (₹)", kind: "money", min: 0.01, max: 100000, required: true, showWhen: (v) => v.wage_type === "piece" },
      { name: "active", label: "Active", kind: "bool" },
    ],
    columns: [
      text("code", "Code", "font-medium"), text("name", "Name"),
      { key: "wage_type", header: "Wage type", cell: (r) => (r.wage_type === "daily" ? "Daily wage" : "Per metre") },
      { key: "rate", header: "Rate", className: "text-right", cell: (r) => (r.wage_type === "daily" ? `${inr(r.daily_rate_paise as number)}/day` : `${inr(r.piece_rate_paise_per_m as number)}/m`) },
      active,
    ],
  },
  {
    path: "shifts", title: "Shifts", singular: "shift", hasActive: false,
    description: "Shift timings. A night shift may end the next morning.",
    fields: [
      { name: "code", label: "Code", kind: "text", required: true, pattern: "[A-Z]", maxLength: 1, hint: "One capital letter, e.g. A" },
      { name: "name", label: "Name", kind: "text", required: true, maxLength: 40 },
      { name: "start_time", label: "Starts", kind: "time", required: true },
      { name: "end_time", label: "Ends", kind: "time", required: true },
    ],
    columns: [
      text("code", "Code", "font-medium"), text("name", "Name"),
      { key: "start", header: "Starts", cell: (r) => (r.start_time as string).slice(0, 5) },
      { key: "end", header: "Ends", cell: (r) => (r.end_time as string).slice(0, 5) },
    ],
  },
];

export const masterByPath = (path: string) => MASTERS.find((m) => m.path === path)!;
