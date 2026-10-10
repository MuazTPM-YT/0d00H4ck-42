// Indian formats everywhere: ₹1,23,456.00, kg for yarn, metres for fabric, IST times.
const TZ = "Asia/Kolkata";

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
const qty = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });

// money travels as integer paise
export const inr = (paise: number | null | undefined) =>
  paise === null || paise === undefined ? "—" : rupees.format(paise / 100);

// whole rupees for wide money tables: ₹1,44,555
const rupees0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
export const inr0 = (paise: number | null | undefined) =>
  paise === null || paise === undefined ? "—" : rupees0.format(Math.round(paise / 100));

// quantities travel as decimal strings ("12.500") to keep exact grams
export const kg = (v: string | number | null | undefined) => (v === null || v === undefined ? "—" : `${qty.format(Number(v))} kg`);
export const metres = (v: string | number | null | undefined) => (v === null || v === undefined ? "—" : `${qty.format(Number(v))} m`);

export const date = (iso: string | null | undefined) =>
  iso ? new Date(iso.length === 10 ? `${iso}T00:00:00+05:30` : iso).toLocaleDateString("en-IN", { timeZone: TZ, day: "numeric", month: "short", year: "numeric" }) : "—";

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: TZ, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

// "1,234.5" rupees typed in a form -> 123450 paise, without float rounding
export function rupeesToPaise(input: string): number | null {
  const clean = input.replace(/[,₹\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null;
  const [whole, frac = ""] = clean.split(".");
  return Number(whole) * 100 + Number(frac.padEnd(2, "0"));
}

export const paiseToRupees = (paise: number | null | undefined) =>
  paise === null || paise === undefined ? "" : (paise / 100).toFixed(2);

// snake_case status -> "Awaiting qc" style label
export const humanize = (s: string) => s.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
