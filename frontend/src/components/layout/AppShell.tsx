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
  const allowed = !route || canSee(route, user.role);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[16.5rem_1fr]">
      <aside className="sticky top-0 z-20 hidden h-dvh md:block">
        <Sidebar user={user} />
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="material sticky top-0 z-30 grid min-h-16 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-1 border-b border-border/60 px-2 py-2 md:hidden">
          <div className="flex min-w-0 items-center gap-1">
            <Button variant="ghost" size="icon" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
              <Menu className="size-6" />
            </Button>
            <span className="min-w-0 text-[1.125rem] leading-tight font-semibold tracking-tight [overflow-wrap:anywhere]">{route?.title ?? "Everest"}</span>
          </div>
          <Link
            href={roleHome(user.role)}
            aria-label="Go to home page"
            className="relative block size-8 outline-none before:absolute before:-inset-1.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <BrandMark className="size-8" />
          </Link>
        </header>
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetContent side="left" className="w-72 border-0 p-0" showCloseButton={false}>
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <Sidebar user={user} onNavigate={() => setMenuOpen(false)} />
          </SheetContent>
        </Sheet>

        <main className="mx-auto min-w-0 w-full max-w-7xl flex-1 px-4 pt-6 pb-16 sm:px-6 lg:px-10 lg:pt-10">
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
