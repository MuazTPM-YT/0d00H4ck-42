// Partial edits stay editable; signs, exponents and pasted junk never become quantities.
export function acceptsNumericEdit(value: string, integer = false): boolean {
  return integer ? /^\d*$/.test(value) : /^\d*(\.\d*)?$/.test(value);
}

export function validQuantity(value: string, max = 999_999_999.999, decimals = 3, min = 0.001): boolean {
  return new RegExp(`^\\d+(\\.\\d{1,${decimals}})?$`).test(value)
    && Number.isFinite(Number(value)) && Number(value) >= min && Number(value) <= max;
}

// All calendar limits follow the mill's IST date, including before 05:30 UTC.
export function millDate(days = 0, now = Date.now()): string {
  return new Date(now + days * 86_400_000).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export function validDate(value: string, min?: string, max?: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
    && (!min || value >= min) && (!max || value <= max);
}
