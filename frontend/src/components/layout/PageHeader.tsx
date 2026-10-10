"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";

import { SECTION_TINT, WeaveArt } from "@/components/layout/WeaveArt";
import { breadcrumbs, findRoute } from "@/nav";

// every page opens on a banner: where you came from, a big icon + title, a patch of the
// section's cloth on the right, and the primary action top right
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  const pathname = usePathname();
  const crumbs = breadcrumbs(pathname);
  // the nearest menu item, so a detail page wears its section's icon and colour
  const section = [...crumbs].reverse().map((c) => findRoute(c.href)?.nav).find(Boolean);
  const Icon = section?.icon;
  const tint = SECTION_TINT[section?.group ?? ""] ?? SECTION_TINT.Setup;
  const seed = [...(section?.group ?? title)].reduce((n, ch) => n + ch.charCodeAt(0), 0);

  return (
    <header className="relative mb-8 overflow-hidden rounded-[1.75rem] bg-card shadow-card">
      <WeaveArt seed={seed} tint={tint} className="pointer-events-none absolute inset-y-0 right-0 h-full w-[62%] opacity-90" />
      <div
        className="pointer-events-none absolute -top-24 -left-16 size-72 rounded-full opacity-[0.14] blur-3xl"
        style={{ background: tint }}
        aria-hidden
      />
      <div className="relative flex flex-col gap-5 p-6 sm:flex-row sm:items-end sm:justify-between sm:p-8">
        <div className="flex min-w-0 items-start gap-4">
          {Icon && (
            <span
              className="grid size-16 shrink-0 place-items-center rounded-[1.25rem] text-white shadow-raised"
              style={{ background: `linear-gradient(145deg, ${tint}, color-mix(in srgb, ${tint} 55%, #000))` }}
              aria-hidden
            >
              <Icon className="size-8" strokeWidth={1.8} />
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
            <h1 className="truncate text-[1.85rem] font-bold sm:text-[2.2rem]">{title}</h1>
            {description && <p className="mt-1.5 max-w-xl text-[0.97rem] text-muted-foreground">{description}</p>}
          </div>
        </div>
        {actions && <div className="relative flex shrink-0 flex-wrap gap-2">{actions}</div>}
      </div>
    </header>
  );
}
