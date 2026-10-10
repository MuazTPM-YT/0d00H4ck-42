"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BrandMark } from "@/components/layout/BrandMark";
import { ROLE_LABEL, type User, useLogout } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { navFor, ROUTES } from "@/nav";

// active = this item, or a child page that is not its own menu item
function isActive(pathname: string, href: string) {
  if (pathname === href) return true;
  if (!pathname.startsWith(`${href}/`)) return false;
  return !ROUTES.some((r) => r.nav && r.path !== href && r.path.startsWith(`${href}/`) && pathname.startsWith(r.path));
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");

// sidebar: big tap targets, one filled pill marks where you are
export function Sidebar({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const logout = useLogout();

  return (
    <div className="flex h-full bg-sidebar flex-col border-r border-border/70 text-sidebar-foreground">
      <div className="flex items-center gap-3 px-5 pt-6 pb-5">
        <BrandMark />
        <div className="min-w-0 leading-tight">
          <p className="truncate text-[1.05rem] font-semibold tracking-tight">Everest</p>
          <p className="truncate text-[0.8rem] text-sidebar-muted">Textile Mills</p>
        </div>
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pb-4">
        {navFor(user.role).map(({ group, items }) => (
          <div key={group} className="mt-5 first:mt-0">
            <p className="px-3 pb-1.5 text-[0.75rem] font-semibold text-sidebar-muted">{group}</p>
            <ul className="grid gap-1">
              {items.map((item) => {
                const active = isActive(pathname, item.path);
                const Icon = item.nav!.icon;
                return (
                  <li key={item.path}>
                    <Link
                      href={item.path}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "pressable flex h-11 items-center gap-3 rounded-xl px-3 text-[0.94rem] font-medium",
                        active
                          ? "bg-sidebar-active text-sidebar-active-foreground shadow-sm"
                          : "text-sidebar-foreground/85 hover:bg-sidebar-hover hover:text-sidebar-foreground",
                      )}
                    >
                      <Icon className="size-5 shrink-0" strokeWidth={active ? 2.25 : 1.9} aria-hidden />
                      <span className="truncate">{item.title}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="m-3 flex items-center gap-3 rounded-2xl bg-card/70 p-3 shadow-card">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-secondary text-sm font-semibold text-secondary-foreground" aria-hidden>
          {initials(user.name)}
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-[0.9rem] font-semibold">{user.name}</p>
          <p className="truncate text-[0.78rem] text-sidebar-muted">{ROLE_LABEL[user.role]}</p>
        </div>
        <button
          type="button"
          onClick={() => logout.mutate()}
          aria-label="Log out"
          title="Log out"
          className="pressable grid size-10 shrink-0 place-items-center rounded-full text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
        >
          <LogOut className="size-[1.15rem]" aria-hidden />
        </button>
      </div>
    </div>
  );
}
