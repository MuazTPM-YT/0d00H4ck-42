"use client";

import { LogOut, Moon, Pause, Play, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { SECTION } from "@/components/dither/motifs";
import { setMotion, useMotion } from "@/components/dither/ticker";
import { BrandMark } from "@/components/layout/BrandMark";
import { TourButton } from "@/features/tour/Tour";
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

// paper by default; ink on request, remembered per browser (layout.tsx applies it before paint)
function useTheme() {
  const [ink, setInk] = useState(false);
  useEffect(() => setInk(document.documentElement.dataset.theme === "dark"), []);
  const toggle = () => {
    const next = !ink;
    setInk(next);
    if (next) document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {}
  };
  return { ink, toggle };
}

// sidebar: big tap targets, mono section labels with their ledger index, ink bar marks where you are
export function Sidebar({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const logout = useLogout();
  const theme = useTheme();
  const motion = useMotion();

  return (
    <div className="flex h-full bg-sidebar flex-col border-r border-border/70 text-sidebar-foreground">
      <div className="flex items-center gap-3 px-5 pt-6 pb-5">
        <BrandMark />
        <div className="min-w-0 leading-tight">
          <p className="truncate font-display text-[1.45rem] leading-none font-medium">Everest</p>
          <p className="label mt-1 truncate">Textile Mills</p>
        </div>
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pb-4">
        {navFor(user.role).map(({ group, items }) => (
          <div key={group} className="mt-5 first:mt-0">
            <p className="label flex items-center gap-2 border-b border-border px-3 pb-1.5 mb-1.5">
              <span className="text-sidebar-accent">{SECTION[group]?.index ?? "00"}</span>
              {group}
            </p>
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
                        "pressable relative flex h-11 items-center gap-3 px-3 text-[0.94rem] font-medium",
                        active
                          ? "bg-sidebar-active text-sidebar-active-foreground before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-sidebar-accent"
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

      <TourButton className="mx-3 h-9 text-[0.85rem]" />

      <div className="m-3 flex items-center gap-2 border-t border-foreground pt-3">
        <span className="grid size-10 shrink-0 place-items-center border border-foreground font-mono text-sm font-medium" aria-hidden>
          {initials(user.name)}
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-[0.9rem] font-semibold">{user.name}</p>
          <p className="label truncate">{ROLE_LABEL[user.role]}</p>
        </div>
        <button
          type="button"
          onClick={theme.toggle}
          aria-label={theme.ink ? "Switch to paper" : "Switch to ink"}
          title={theme.ink ? "Paper" : "Ink"}
          className="pressable grid size-9 shrink-0 place-items-center text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
        >
          {theme.ink ? <Sun className="size-[1.1rem]" aria-hidden /> : <Moon className="size-[1.1rem]" aria-hidden />}
        </button>
        <button
          type="button"
          onClick={() => setMotion(!motion)}
          aria-pressed={motion}
          aria-label={motion ? "Stop the moving pictures" : "Let the pictures move"}
          title={motion ? "Motion on" : "Motion off"}
          className="pressable grid size-9 shrink-0 place-items-center text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
        >
          {motion ? <Pause className="size-[1.05rem]" aria-hidden /> : <Play className="size-[1.05rem]" aria-hidden />}
        </button>
        <button
          type="button"
          onClick={() => logout.mutate()}
          aria-label="Log out"
          title="Log out"
          className="pressable grid size-9 shrink-0 place-items-center text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
        >
          <LogOut className="size-[1.15rem]" aria-hidden />
        </button>
      </div>
    </div>
  );
}
