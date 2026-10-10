"use client";

import { Lock, Menu, WifiOff } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { BrandMark } from "@/components/layout/BrandMark";
import { EmptyState } from "@/components/layout/EmptyState";
import { Sidebar } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { ApiError } from "@/lib/api";
import { roleHome, useMe } from "@/lib/auth";
import { canSee, findRoute } from "@/nav";

// sidebar on laptops, slide-in menu on phones; hides screens the role cannot use
// (the API enforces roles too: this guard is for clarity, not security)
export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const route = findRoute(pathname);

  // each tab names its screen, so office users with many tabs can tell them apart
  useEffect(() => {
    document.title = route ? `${route.title} · Everest` : "Everest Textile Mills";
  }, [route]);

  if (me.error instanceof ApiError && me.error.status === 0) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <EmptyState icon={WifiOff} title="Can't reach the mill server" action={<Button onClick={() => me.refetch()}>Try again</Button>}>
          Check that this tablet is on the mill Wi-Fi and the server is switched on.
        </EmptyState>
      </div>
    );
  }

  if (!me.data) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <div className="flex flex-col items-center gap-4 text-muted-foreground">
          <BrandMark className="size-14 animate-pulse rounded-2xl" />
          <p className="text-sm">{me.isError ? "Checking your login…" : "Opening Everest…"}</p>
        </div>
      </div>
    );
  }

  const user = me.data;
  // a page missing from the route table is refused, not open to everyone
  const allowed = !!route && canSee(route, user.role);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[16.5rem_1fr]">
      <aside className="sticky top-0 z-20 hidden h-dvh md:block">
        <Sidebar user={user} />
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="material sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border/60 px-3 md:hidden">
          <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu className="size-6" />
          </Button>
          <BrandMark className="size-8" />
          <span className="text-[1.05rem] font-semibold tracking-tight">{route?.title ?? "Everest"}</span>
        </header>
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetContent side="left" className="w-72 border-0 p-0" showCloseButton={false}>
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <Sidebar user={user} onNavigate={() => setMenuOpen(false)} />
          </SheetContent>
        </Sheet>

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-6 pb-16 sm:px-6 lg:px-10 lg:pt-10">
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
