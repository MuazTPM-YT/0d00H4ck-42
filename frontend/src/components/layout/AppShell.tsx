"use client";

import { Lock, Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { Sidebar } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { roleHome, useMe } from "@/lib/auth";
import { canSee, findRoute } from "@/nav";

// sidebar on laptops, slide-in menu on phones; hides screens the role cannot use
// (the API enforces roles too: this guard is for clarity, not security)
export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  if (!me.data) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        {me.isError ? (
          <p className="text-sm text-muted-foreground">Checking your login…</p>
        ) : (
          <Skeleton className="h-8 w-48" />
        )}
      </div>
    );
  }

  const user = me.data;
  const route = findRoute(pathname);
  const allowed = !route || canSee(route, user.role);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <aside className="sticky top-0 hidden h-dvh md:block">
        <Sidebar user={user} />
      </aside>

      <div className="flex min-w-0 flex-col">
        <div className="weave sticky top-0 z-30 flex items-center gap-3 px-4 py-3 text-white md:hidden">
          <Button variant="ghost" size="icon" aria-label="Open menu" className="text-white hover:bg-white/10 hover:text-white" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <span className="font-semibold">Everest Textile Mills</span>
        </div>
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetContent side="left" className="w-72 border-0 p-0">
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <Sidebar user={user} onNavigate={() => setMenuOpen(false)} />
          </SheetContent>
        </Sheet>

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {allowed ? (
            children
          ) : (
            <EmptyState icon={Lock} title="This screen is not part of your role" action={<Button asChild variant="outline"><Link href={roleHome(user.role)}>Go to my home</Link></Button>}>
              Ask the owner if you need access.
            </EmptyState>
          )}
        </main>
      </div>
    </div>
  );
}
