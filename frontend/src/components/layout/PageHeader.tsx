"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";

import { breadcrumbs } from "@/nav";

// same skeleton on every page: breadcrumbs, title left, primary action top right
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  const crumbs = breadcrumbs(usePathname());
  return (
    <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {crumbs.length > 1 && (
          <nav aria-label="Breadcrumb" className="mb-1 flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
            {crumbs.slice(0, -1).map((c) => (
              <Fragment key={c.href}>
                <Link href={c.href} className="hover:text-foreground hover:underline">
                  {c.title}
                </Link>
                <span aria-hidden>/</span>
              </Fragment>
            ))}
          </nav>
        )}
        <h1 className="truncate text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
