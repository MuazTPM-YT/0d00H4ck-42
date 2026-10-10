// one fetch wrapper for every backend call; errors come back in one shape
export type Paged<T> = { items: T[]; total: number };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public field: string | null = null,
  ) {
    super(message);
  }
}

type Options = Omit<RequestInit, "body"> & { json?: unknown };

export async function api<T>(path: string, { json, headers, ...init }: Options = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      credentials: "same-origin",
      headers: json === undefined ? headers : { "Content-Type": "application/json", ...headers },
      body: json === undefined ? undefined : JSON.stringify(json),
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the mill server. Check the connection.");
  }

  if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = body?.error;
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? res.statusText, e?.field ?? null);
  }
  return body as T;
}

// every row of a paged list, 200 per request (the API max), for dropdowns and lookups that
// must never cut off silently. ponytail: fine to a few thousand rows; past that use search (q=)
export async function apiAll<T>(path: string): Promise<Paged<T>> {
  const sep = path.includes("?") ? "&" : "?";
  const items: T[] = [];
  for (let total = Infinity; items.length < total; ) {
    const page = await api<Paged<T>>(`${path}${sep}limit=200&offset=${items.length}`);
    items.push(...page.items);
    total = page.items.length ? page.total : items.length;
  }
  return { items, total: items.length };
}

// builds ?a=1&b=2, skipping empty values
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
