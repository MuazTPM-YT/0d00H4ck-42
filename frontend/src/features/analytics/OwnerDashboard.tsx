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
const shortDay = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const lakh = (paise: number) => {
  const r = paise / 100;
  return r >= 1e5 ? `₹${(r / 1e5).toFixed(1)}L` : r >= 1e3 ? `₹${(r / 1e3).toFixed(0)}k` : `₹${r.toFixed(0)}`;
};
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <section className={cn("rounded-3xl bg-card p-5 shadow-card", className)}>{children}</section>;
}

function CardTitle({ title, hint, icon: Icon }: { title: string; hint?: string; icon: LucideIcon }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-[1.05rem] font-semibold">{title}</h2>
        {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
      </div>
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-muted text-foreground" aria-hidden>
        <Icon className="size-[1.1rem]" />
      </span>
    </div>
  );
}

function ChartTip({ active, payload, label, money }: { active?: boolean; payload?: { value: number }[]; label?: string; money?: boolean }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border/60 bg-card px-3 py-2 text-sm shadow-raised">
      <p className="text-muted-foreground">{label}</p>
      <p className="font-semibold tabular">{money ? inr(payload[0].value) : `${num.format(payload[0].value)} m`}</p>
    </div>
  );
}

function Stat({ icon: Icon, label, value, sub, tone = "default" }: { icon: LucideIcon; label: string; value: string; sub: string; tone?: "default" | "good" | "bad" }) {
  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
        <span className="grid size-10 place-items-center rounded-2xl bg-primary text-primary-foreground" aria-hidden>
          <Icon className="size-5" />
        </span>
      </div>
      <div>
        <p className={cn("text-[2rem] leading-none font-bold tracking-tight tabular", tone === "good" && "text-success", tone === "bad" && "text-danger")}>{value}</p>
        <p className="mt-2 text-sm text-muted-foreground">{sub}</p>
      </div>
    </Card>
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
      <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Month">
        {months.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={m === month}
            onClick={() => setPicked(m)}
            className={cn("pressable h-10 rounded-full px-4 text-sm font-medium", m === month ? "bg-primary text-primary-foreground" : "bg-card text-foreground shadow-card hover:bg-accent")}
          >
            {monthName(m)}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {v ? (
          <>
            <Stat icon={TrendingUp} label="Invoiced" value={lakh(v.invoiced_paise)} sub={`${inr(v.invoiced_paise)} incl. GST`} />
            <Stat icon={Banknote} label="Cash received" value={lakh(v.received_paise)} sub={v.invoiced_paise ? `${Math.round((v.received_paise / v.invoiced_paise) * 100)}% of invoiced collected` : "Nothing invoiced yet"} />
            <Stat
              icon={Wallet}
              label="Month result (cash)"
              value={lakh(v.result_cash_paise)}
              sub={`Yarn ${lakh(v.yarn_bills_paise)} · wages ${lakh(v.wages_accrued_paise)} · other ${lakh(v.expenses_paise)}`}
              tone={v.result_cash_paise >= 0 ? "good" : "bad"}
            />
            <Stat icon={Ruler} label="Fabric woven" value={`${num.format(wovenTotal)} m`} sub={`${fabricByDay.length} working days on the looms`} />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-40 rounded-3xl" />)
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-4">
        <Card className="xl:col-span-2">
          <CardTitle title="Invoiced per day" hint={`Sales billed in ${monthName(month)}`} icon={TrendingUp} />
          <div className="h-64">
            {revenueByDay.length ? (
              <ResponsiveContainer>
                <BarChart data={revenueByDay} margin={{ left: 0, right: 4, top: 4 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} minTickGap={12} />
                  <YAxis tickLine={false} axisLine={false} width={52} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} tickFormatter={lakh} />
                  <Tooltip cursor={{ fill: "var(--muted)" }} content={<ChartTip money />} />
                  <Bar dataKey="paise" fill="var(--primary)" radius={[8, 8, 4, 4]} maxBarSize={28} />
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
                  <defs>
                    <linearGradient id="woven" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--foreground)" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="var(--foreground)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} minTickGap={12} />
                  <YAxis tickLine={false} axisLine={false} width={48} tick={{ fill: "var(--muted-foreground)", fontSize: 12 }} />
                  <Tooltip content={<ChartTip />} />
                  <Area type="monotone" dataKey="metres" stroke="var(--foreground)" strokeWidth={2.25} fill="url(#woven)" />
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
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="code" tickLine={false} axisLine={false} width={64} tick={{ fill: "var(--foreground)", fontSize: 13, fontWeight: 600 }} />
                  <Tooltip cursor={{ fill: "var(--muted)" }} content={<ChartTip />} />
                  <Bar dataKey="metres" radius={[4, 10, 10, 4]} barSize={16}>
                    {machineRank.map((m, i) => (
                      <Cell key={m.code} fill={i === 0 ? "var(--primary)" : `color-mix(in srgb, var(--primary) ${Math.max(28, 85 - i * 8)}%, transparent)`} />
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
                  <Pie data={risk} dataKey="value" innerRadius="68%" outerRadius="100%" paddingAngle={3} cornerRadius={8} stroke="none">
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
                  <span className="block text-3xl font-bold tabular">{riskTotal}</span>
                  <span className="text-xs text-muted-foreground">open orders</span>
                </span>
              </div>
            )}
          </div>
          <ul className="mt-4 grid gap-1.5 text-sm">
            {risk.map((r) => (
              <li key={r.key} className="flex items-center justify-between">
                <span className="flex items-center gap-2"><span className="size-2.5 rounded-full" style={{ background: r.color }} />{r.label}</span>
                <span className="font-semibold tabular">{r.value}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <CardTitle title="Go to" icon={ArrowUpRight} />
          <nav className="grid gap-2">
            {ACTIONS.map(({ href, label, icon: Icon }) => (
              <Link key={href} href={href} className="pressable flex h-12 items-center gap-3 rounded-2xl bg-muted/70 px-3 font-medium hover:bg-accent">
                <span className="grid size-8 place-items-center rounded-xl bg-card shadow-card"><Icon className="size-4" /></span>
                {label}
                <ArrowUpRight className="ml-auto size-4 text-muted-foreground" />
              </Link>
            ))}
          </nav>
        </Card>
      </div>
    </div>
  );
}

function EmptyChart({ loading, text }: { loading: boolean; text: string }) {
  if (loading) return <Skeleton className="h-full w-full rounded-2xl" />;
  return <div className="grid h-full place-items-center rounded-2xl bg-muted/50 text-sm text-muted-foreground">{text}</div>;
}
