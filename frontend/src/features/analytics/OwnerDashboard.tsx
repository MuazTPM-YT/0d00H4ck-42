"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Banknote,
  Factory,
  FileText,
  Lightbulb,
  type LucideIcon,
  Ruler,
  ShoppingCart,
  TrendingUp,
  Truck,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { DitherPlate } from "@/components/dither/DitherPlate";
import type { MotifName } from "@/components/dither/motifs";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { DeliveryEstimate } from "./api";

// owner's one-glance mill: money, fabric, machines and delivery risk, all from live rows

type MonthView = {
  month: string;
  invoiced_paise: number;
  received_paise: number;
  yarn_bills_paise: number;
  wages_accrued_paise: number;
  expenses_paise: number;
  result_cash_paise: number;
  result_invoiced_paise: number;
};
type MonthRecord = { on: string; ref: string; party: string; amount_paise: number };
type MachineProduction = { machine_id: number; code: string; name: string; unit: string; month_qty: string; days: { day: string; qty: string }[] };

const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const monthName = (key: string) => new Date(`${key}-01T00:00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
const shortMonth = (key: string) => new Date(`${key}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
const shortDay =(iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
// short rupees for headlines: ₹26.2L, ₹480k, −₹20.8L (the sign goes before the symbol)
const lakh = (paise: number) => {
  const r = Math.abs(paise / 100);
  const sign = paise < 0 ? "−" : "";
  return `${sign}₹${r >= 1e5 ? `${(r / 1e5).toFixed(1)}L` : r >= 1e3 ? `${(r / 1e3).toFixed(0)}k` : r.toFixed(0)}`;
};
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <section className={cn("min-w-0 border border-border bg-card p-5", className)}>{children}</section>;
}

function CardTitle({ title, hint, icon: Icon }: { title: string; hint?: string; icon: LucideIcon }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-[1.55rem] font-normal">{title}</h2>
        {hint && <p className="mt-0.5 text-sm text-muted-foreground">{hint}</p>}
      </div>
      <span className="grid size-9 shrink-0 place-items-center border border-border text-muted-foreground" aria-hidden>
        <Icon className="size-[1.1rem]" />
      </span>
    </div>
  );
}

function ChartTip({ active, payload, label, money }: { active?: boolean; payload?: { value: number }[]; label?: string; money?: boolean }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="border border-foreground bg-card px-3 py-2 text-sm">
      <p className="label">{label}</p>
      <p className="num font-medium">{money ? inr(payload[0].value) : `${num.format(payload[0].value)} m`}</p>
    </div>
  );
}

// one ledger figure: mono label, big dotted numeral, a small print of where the number comes from
function Stat({ icon: Icon, label, value, sub, motif, tone = "default" }: { icon: LucideIcon; label: string; value: string; sub: string; motif: MotifName; tone?: "default" | "good" | "bad" }) {
  return (
    <Card className="relative flex flex-col gap-4 overflow-hidden border-t-foreground">
      {/* a faint print in the corner, under nothing that has to be read */}
      <DitherPlate motif={motif} seed={label} className="pointer-events-none absolute! right-0 bottom-0 h-16! w-28! opacity-35 [mask-image:linear-gradient(to_left,#000,transparent)]" />
      <span className="relative flex min-w-0 items-center gap-2">
        <Icon className="size-4 shrink-0 text-ember" aria-hidden />
        <span className="label">{label}</span>
      </span>
      <div className="relative min-w-0">
        <p className={cn("figure truncate text-[2.25rem]", tone === "good" && "text-success", tone === "bad" && "text-danger")}>{value}</p>
        <p className="mt-2 text-sm text-body">{sub}</p>
      </div>
    </Card>
  );
}

// 1-bit fills for the charts: ink at half density, like the dithered plates
function Halftones() {
  return (
    <defs>
      <pattern id="ink-dots" width="4" height="4" patternUnits="userSpaceOnUse">
        <rect width="2" height="2" fill="var(--foreground)" />
        <rect x="2" y="2" width="2" height="2" fill="var(--foreground)" />
      </pattern>
      <pattern id="ink-sparse" width="6" height="6" patternUnits="userSpaceOnUse">
        <rect width="1.5" height="1.5" fill="var(--foreground)" />
        <rect x="3" y="3" width="1.5" height="1.5" fill="var(--foreground)" />
      </pattern>
      <pattern id="ember-dots" width="4" height="4" patternUnits="userSpaceOnUse">
        <rect width="2" height="2" fill="var(--ember)" />
        <rect x="2" y="2" width="2" height="2" fill="var(--ember)" />
      </pattern>
    </defs>
  );
}

const RISK = [
  { key: "on_track", label: "On track", color: "var(--success)" },
  { key: "at_risk", label: "At risk", color: "var(--warning)" },
  { key: "late", label: "Late", color: "var(--danger)" },
] as const;

const ACTIONS: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/floor", label: "Floor board", icon: Factory },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/insights", label: "Insights", icon: Lightbulb },
  { href: "/finance/month", label: "Month-end", icon: FileText },
  { href: "/dispatch", label: "Dispatch", icon: Truck },
];

export function OwnerDashboard() {
  const now = new Date();
  const months = [0, 1, 2].map((back) => monthKey(new Date(now.getFullYear(), now.getMonth() - back, 1)));
  const [picked, setPicked] = useState<string | null>(null);

  const thisMonth = useQuery({ queryKey: ["orders", "month", months[0]], queryFn: () => api<MonthView>(`/finance/month?month=${months[0]}`) });
  const lastMonth = useQuery({ queryKey: ["orders", "month", months[1]], queryFn: () => api<MonthView>(`/finance/month?month=${months[1]}`) });
  // open on the latest month that has sales, so a fresh month never greets the owner with zeros
  const month = picked ?? (thisMonth.data && thisMonth.data.invoiced_paise === 0 && (lastMonth.data?.invoiced_paise ?? 0) > 0 ? months[1] : months[0]);

  const view = useQuery({ queryKey: ["orders", "month", month], queryFn: () => api<MonthView>(`/finance/month?month=${month}`) });
  const invoiced = useQuery({ queryKey: ["orders", "month-invoiced", month], queryFn: () => api<MonthRecord[]>(`/finance/month/records?month=${month}&kind=invoiced`) });
  const machines = useQuery({ queryKey: ["machines", "month", month], queryFn: () => api<MachineProduction[]>(`/finance/machine-production?month=${month}`) });
  const delivery = useQuery({ queryKey: ["orders", "delivery"], queryFn: () => api<DeliveryEstimate[]>("/analytics/delivery") });

  const revenueByDay = useMemo(() => {
    const byDay = new Map<string, number>();
    for (const r of invoiced.data ?? []) byDay.set(r.on.slice(0, 10), (byDay.get(r.on.slice(0, 10)) ?? 0) + r.amount_paise);
    return [...byDay].sort(([a], [b]) => a.localeCompare(b)).map(([day, paise]) => ({ day: shortDay(day), paise }));
  }, [invoiced.data]);

  const fabricByDay = useMemo(() => {
    const byDay = new Map<string, number>();
    for (const m of machines.data ?? []) {
      if (m.unit !== "m" || !m.code.startsWith("LM")) continue;
      for (const d of m.days) byDay.set(d.day, (byDay.get(d.day) ?? 0) + Number(d.qty));
    }
    return [...byDay].sort(([a], [b]) => a.localeCompare(b)).map(([day, metres]) => ({ day: shortDay(day), metres: Math.round(metres) }));
  }, [machines.data]);

  const machineRank = useMemo(
    () =>
      (machines.data ?? [])
        .filter((m) => m.unit === "m")
        .map((m) => ({ code: m.code, metres: Math.round(Number(m.month_qty)) }))
        .sort((a, b) => b.metres - a.metres),
    [machines.data],
  );

  const risk = useMemo(() => RISK.map((r) => ({ ...r, value: (delivery.data ?? []).filter((d) => d.status === r.key).length })), [delivery.data]);
  const riskTotal = risk.reduce((s, r) => s + r.value, 0);
  const wovenTotal = fabricByDay.reduce((s, d) => s + d.metres, 0);
  const v = view.data;

  return (
    <div className="grid gap-4">
      {/* one row always: equal thirds on a phone with short names, full names from sm up */}
      <div className="flex items-center gap-2" role="radiogroup" aria-label="Month">
        {months.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={m === month}
            aria-label={monthName(m)}
            onClick={() => setPicked(m)}
            className={cn("pressable h-10 min-w-0 flex-1 whitespace-nowrap border px-2 text-[0.88rem] font-medium sm:flex-none sm:px-4", m === month ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card text-foreground hover:border-foreground")}
          >
            <span className="sm:hidden">{shortMonth(m)}</span>
            <span className="hidden sm:inline">{monthName(m)}</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {v ? (
          <>
            <Stat motif="orders" icon={TrendingUp} label="Invoiced" value={lakh(v.invoiced_paise)} sub={`${inr(v.invoiced_paise)} incl. GST`} />
            <Stat motif="bars" icon={Banknote} label="Cash received" value={lakh(v.received_paise)} sub={v.invoiced_paise ? `${Math.round((v.received_paise / v.invoiced_paise) * 100)}% of invoiced collected` : "Nothing invoiced yet"} />
            <Stat
              motif="mill"
              icon={Wallet}
              label="Month result (cash)"
              value={lakh(v.result_cash_paise)}
              sub={`Yarn ${lakh(v.yarn_bills_paise)} · wages ${lakh(v.wages_accrued_paise)} · other ${lakh(v.expenses_paise)}`}
              tone={v.result_cash_paise >= 0 ? "good" : "bad"}
            />
            <Stat motif="loom" icon={Ruler} label="Fabric woven" value={`${num.format(wovenTotal)} m`} sub={`${fabricByDay.length} working days on the looms`} />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-40" />)
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <Card className="xl:col-span-2">
          <CardTitle title="Invoiced per day" hint={`Sales billed in ${monthName(month)}`} icon={TrendingUp} />
          <div className="h-64">
            {revenueByDay.length ? (
              <ResponsiveContainer>
                <BarChart data={revenueByDay} margin={{ left: 0, right: 4, top: 4 }}>
                  <Halftones />
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} minTickGap={12} />
                  <YAxis tickLine={false} axisLine={false} width={52} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} tickFormatter={lakh} />
                  <Tooltip cursor={{ fill: "var(--muted)" }} content={<ChartTip money />} />
                  <Bar dataKey="paise" fill="url(#ink-dots)" stroke="var(--foreground)" strokeWidth={1} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart loading={invoiced.isPending} text="No invoices this month yet" />
            )}
          </div>
        </Card>

        <Card className="xl:col-span-2">
          <CardTitle title="Fabric woven per day" hint="Metres off every loom, from machine output logs" icon={Ruler} />
          <div className="h-64">
            {fabricByDay.length ? (
              <ResponsiveContainer>
                <AreaChart data={fabricByDay} margin={{ left: 0, right: 4, top: 4 }}>
                  <Halftones />
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} minTickGap={12} />
                  <YAxis tickLine={false} axisLine={false} width={48} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} />
                  <Tooltip content={<ChartTip />} />
                  <Area type="step" dataKey="metres" stroke="var(--ember)" strokeWidth={2} fill="url(#ink-sparse)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart loading={machines.isPending} text="No loom output logged this month" />
            )}
          </div>
        </Card>

        <Card className="xl:col-span-2">
          <CardTitle title="Output by machine" hint="Metres this month, busiest first" icon={Factory} />
          <div className="h-64">
            {machineRank.length ? (
              <ResponsiveContainer>
                <BarChart data={machineRank} layout="vertical" margin={{ left: 4, right: 12 }}>
                  <Halftones />
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="code" tickLine={false} axisLine={false} width={64} tick={{ fill: "var(--foreground)", fontSize: 12, fontFamily: "var(--font-mono)" }} />
                  <Tooltip cursor={{ fill: "var(--muted)" }} content={<ChartTip />} />
                  <Bar dataKey="metres" barSize={14} strokeWidth={1}>
                    {machineRank.map((m, i) => (
                      <Cell key={m.code} fill={i === 0 ? "url(#ember-dots)" : "url(#ink-dots)"} stroke={i === 0 ? "var(--ember)" : "var(--foreground)"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart loading={machines.isPending} text="No machine output this month" />
            )}
          </div>
        </Card>

        <Card>
          <CardTitle title="Delivery risk" hint="Open orders vs deadline" icon={Truck} />
          <div className="relative h-44">
            {riskTotal ? (
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={risk} dataKey="value" innerRadius="70%" outerRadius="100%" paddingAngle={2} stroke="var(--card)" strokeWidth={2}>
                    {risk.map((r) => <Cell key={r.key} fill={r.color} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart loading={delivery.isPending} text="No open orders" />
            )}
            {riskTotal > 0 && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
                <span>
                  <span className="figure block text-4xl">{riskTotal}</span>
                  <span className="label">open orders</span>
                </span>
              </div>
            )}
          </div>
          <ul className="mt-4 grid gap-1.5 text-sm">
            {risk.map((r) => (
              <li key={r.key} className="flex items-center justify-between border-t border-border pt-1.5 first:border-foreground">
                <span className="flex items-center gap-2"><span className="dot size-2.5" style={{ background: r.color }} />{r.label}</span>
                <span className="num font-medium">{r.value}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <CardTitle title="Go to" icon={ArrowUpRight} />
          <nav className="grid">
            {ACTIONS.map(({ href, label, icon: Icon }, i) => (
              <Link key={href} href={href} className="dither-hover group flex h-12 items-center gap-3 border-t border-border px-1 font-medium first:border-foreground hover:text-ember">
                <span className="num w-6 text-[0.78rem] text-ember">{String(i + 1).padStart(2, "0")}</span>
                <Icon className="size-4" />
                {label}
                <ArrowUpRight className="ml-auto size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
              </Link>
            ))}
          </nav>
        </Card>
      </div>
    </div>
  );
}

function EmptyChart({ loading, text }: { loading: boolean; text: string }) {
  if (loading) return <Skeleton className="h-full w-full" />;
  return <div className="label grid h-full place-items-center border border-dashed border-border">{text}</div>;
}
