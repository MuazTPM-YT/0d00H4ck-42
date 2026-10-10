"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";

import { breadcrumbs, findRoute } from "@/nav";

// same skeleton on every page: where you came from, a big icon + title, primary action top right
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  const pathname = usePathname();
  const crumbs = breadcrumbs(pathname);
  // the icon of the nearest menu item, so a detail page wears its section's icon
  const Icon = [...crumbs].reverse().map((c) => findRoute(c.href)?.nav?.icon).find(Boolean);

  return (
    <header className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="flex min-w-0 items-start gap-4">
        {Icon && (
          <span className="hidden size-14 shrink-0 place-items-center rounded-2xl bg-card text-foreground shadow-card sm:grid" aria-hidden>
            <Icon className="size-7" strokeWidth={1.8} />
          </span>
        )}
        <div className="min-w-0">
          {crumbs.length > 1 && (
            <nav aria-label="Breadcrumb" className="mb-1 flex flex-wrap items-center gap-0.5 text-[0.88rem] text-muted-foreground">
              {crumbs.slice(0, -1).map((c) => (
                <Fragment key={c.href}>
                  <Link href={c.href} className="rounded-md px-0.5 font-medium hover:text-foreground">
                    {c.title}
                  </Link>
                  <ChevronRight className="size-3.5 opacity-60" aria-hidden />
                </Fragment>
              ))}
            </nav>
          )}
          <h1 className="truncate text-[1.75rem] font-bold sm:text-[2rem]">{title}</h1>
          {description && <p className="mt-1.5 max-w-2xl text-[0.97rem] text-muted-foreground">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
