"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ROLE_LABEL, type User, useLogout } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { navFor, ROUTES } from "@/nav";

// active = this item, or a child page that is not its own menu item
function isActive(pathname: string, href: string) {
  if (pathname === href) return true;
  if (!pathname.startsWith(`${href}/`)) return false;
  return !ROUTES.some((r) => r.nav && r.path !== href && r.path.startsWith(`${href}/`) && pathname.startsWith(r.path));
}

export function Sidebar({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const logout = useLogout();

  return (
    <div className="weave flex h-full flex-col text-sidebar-foreground">
      <div className="px-5 pt-6 pb-4">
        <p className="text-lg font-semibold tracking-tight text-white">Everest Textile Mills</p>
        <p className="text-sm text-sidebar-muted">Yarn to dispatch</p>
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pb-4">
        {navFor(user.role).map(({ group, items }) => (
          <div key={group} className="mt-4 first:mt-0">
            <p className="px-2 pb-1 text-xs font-medium text-sidebar-muted">{group}</p>
            <ul className="grid gap-0.5">
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
                        "flex items-center gap-3 rounded-md border-l-2 border-transparent px-2 py-2 text-sm transition-colors",
                        "hover:bg-sidebar-active hover:text-white focus-visible:outline-2 focus-visible:outline-sidebar-accent",
                        active && "border-sidebar-accent bg-sidebar-active font-medium text-white",
                      )}
                    >
                      <Icon className="size-4 shrink-0" aria-hidden />
                      {item.title}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/10 px-5 py-4">
        <p className="truncate text-sm font-medium text-white">{user.name}</p>
        <p className="text-xs text-sidebar-muted">{ROLE_LABEL[user.role]}</p>
        <button
          type="button"
          onClick={() => logout.mutate()}
          className="mt-3 inline-flex items-center gap-2 text-sm text-sidebar-muted hover:text-white focus-visible:outline-2 focus-visible:outline-sidebar-accent"
        >
          <LogOut className="size-4" aria-hidden />
          Log out
        </button>
      </div>
    </div>
  );
}
