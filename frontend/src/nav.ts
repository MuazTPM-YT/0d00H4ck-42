import {
  Activity,
  Boxes,
  ClipboardCheck,
  ClipboardList,
  Factory,
  FileText,
  Gauge,
  IndianRupee,
  Layers,
  Lightbulb,
  type LucideIcon,
  PackageCheck,
  PackageOpen,
  Settings2,
  ShoppingCart,
  Truck,
  Users,
  Wallet,
  Warehouse,
} from "lucide-react";

import type { Role } from "@/lib/auth";

// Every screen in the app, in one table. Drives the sidebar, breadcrumbs and the page guard.
// Module owners never edit this file or the route folders' existence; they fill in pages.
export type AppRoute = {
  path: string; // "[id]" marks a dynamic segment
  title: string;
  roles: Role[]; // owner passes every check anyway (owner = admin)
  module: string;
  owner: string;
  nav?: { group: string; icon: LucideIcon };
};

export const ROUTES: AppRoute[] = [
  { path: "/owner", title: "Overview", roles: ["owner"], module: "analytics", owner: "Muaz", nav: { group: "Mill", icon: Gauge } },
  { path: "/insights", title: "Insights", roles: ["owner", "supervisor", "store", "qc"], module: "analytics", owner: "Muaz", nav: { group: "Mill", icon: Lightbulb } },

  { path: "/store", title: "Store", roles: ["store"], module: "inventory", owner: "Ammaar", nav: { group: "Yarn store", icon: Warehouse } },
  { path: "/store/receive", title: "Receive yarn", roles: ["store"], module: "inventory", owner: "Ammaar", nav: { group: "Yarn store", icon: PackageOpen } },
  { path: "/store/receive/labels", title: "Sample labels", roles: ["store"], module: "inventory", owner: "Ammaar" },
  { path: "/store/batches", title: "Yarn batches", roles: ["store"], module: "inventory", owner: "Ammaar", nav: { group: "Yarn store", icon: Layers } },
  { path: "/store/stock", title: "Yarn stock", roles: ["store"], module: "inventory", owner: "Ammaar", nav: { group: "Yarn store", icon: Boxes } },

  { path: "/orders", title: "Orders", roles: ["accounts", "owner"], module: "orders", owner: "Ammaar", nav: { group: "Sales", icon: ShoppingCart } },
  { path: "/orders/new", title: "New order", roles: ["accounts", "owner"], module: "orders", owner: "Ammaar" },
  { path: "/orders/[id]", title: "Order", roles: ["accounts", "owner", "dispatch"], module: "tracking", owner: "Ashil" },

  { path: "/floor", title: "Floor board", roles: ["supervisor"], module: "production", owner: "Muaz", nav: { group: "Production", icon: Factory } },
  { path: "/floor/work-orders", title: "Work orders", roles: ["supervisor"], module: "production", owner: "Muaz", nav: { group: "Production", icon: ClipboardList } },
  { path: "/floor/crew", title: "Crew and attendance", roles: ["supervisor"], module: "workforce", owner: "Muaz", nav: { group: "Production", icon: Users } },

  { path: "/qc", title: "QC queue", roles: ["qc"], module: "quality", owner: "Razan", nav: { group: "Quality", icon: ClipboardCheck } },
  { path: "/qc/rolls/[id]", title: "Roll", roles: ["qc", "supervisor", "dispatch", "accounts"], module: "quality", owner: "Razan" },

  { path: "/dispatch", title: "Dispatches", roles: ["dispatch"], module: "dispatch", owner: "Ashil", nav: { group: "Dispatch", icon: Truck } },
  { path: "/dispatch/[id]", title: "Dispatch", roles: ["dispatch", "supervisor", "accounts"], module: "dispatch", owner: "Ashil" },
  { path: "/stock/finished", title: "Finished stock", roles: ["dispatch"], module: "dispatch", owner: "Ashil", nav: { group: "Dispatch", icon: PackageCheck } },

  { path: "/finance/invoices", title: "Invoices", roles: ["accounts", "owner"], module: "finance", owner: "Ashil", nav: { group: "Accounts", icon: FileText } },
  { path: "/finance/payments", title: "Payments", roles: ["accounts", "owner"], module: "finance", owner: "Ashil", nav: { group: "Accounts", icon: IndianRupee } },
  { path: "/finance/wages", title: "Wages", roles: ["accounts", "owner"], module: "finance", owner: "Ashil", nav: { group: "Accounts", icon: Wallet } },
  { path: "/finance/month", title: "Month-end", roles: ["accounts", "owner"], module: "finance", owner: "Ashil", nav: { group: "Accounts", icon: Activity } },

  { path: "/masters", title: "Masters", roles: ["owner"], module: "masters", owner: "Muaz", nav: { group: "Setup", icon: Settings2 } },
  { path: "/masters/suppliers", title: "Suppliers", roles: ["owner"], module: "masters", owner: "Muaz" },
  { path: "/masters/buyers", title: "Buyers", roles: ["owner"], module: "masters", owner: "Muaz" },
  { path: "/masters/yarn-items", title: "Yarn items", roles: ["owner"], module: "masters", owner: "Muaz" },
  { path: "/masters/fabric-types", title: "Fabric types", roles: ["owner"], module: "masters", owner: "Muaz" },
  { path: "/masters/machines", title: "Machines", roles: ["owner"], module: "masters", owner: "Muaz" },
  { path: "/masters/workers", title: "Workers", roles: ["owner"], module: "masters", owner: "Muaz" },
  { path: "/masters/shifts", title: "Shifts", roles: ["owner"], module: "masters", owner: "Muaz" },
];

const toRegex = (path: string) => new RegExp(`^${path.replace(/\[[^/]+\]/g, "[^/]+")}$`);

export function findRoute(pathname: string): AppRoute | undefined {
  return ROUTES.find((r) => toRegex(r.path).test(pathname));
}

export const canSee = (route: AppRoute, role: Role) => role === "owner" || route.roles.includes(role);

// sidebar: only what this role works with (owner sees owner screens, not every screen)
export function navFor(role: Role): { group: string; items: AppRoute[] }[] {
  const groups = new Map<string, AppRoute[]>();
  for (const r of ROUTES) {
    if (!r.nav || !r.roles.includes(role)) continue;
    groups.set(r.nav.group, [...(groups.get(r.nav.group) ?? []), r]);
  }
  return [...groups].map(([group, items]) => ({ group, items }));
}

// "/store/batches" -> Store › Yarn batches; "/orders/42" -> Orders › Order
export function breadcrumbs(pathname: string): { href: string; title: string }[] {
  const parts = pathname.split("/").filter(Boolean);
  const crumbs: { href: string; title: string }[] = [];
  for (let i = 1; i <= parts.length; i++) {
    const href = `/${parts.slice(0, i).join("/")}`;
    const route = findRoute(href);
    if (route) crumbs.push({ href, title: route.title });
  }
  return crumbs;
}
