"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";

import { DitherPlate } from "@/components/dither/DitherPlate";
import { SECTION } from "@/components/dither/motifs";
import { breadcrumbs, findRoute } from "@/nav";

// every page opens on a ledger header: "04 · PRODUCTION" eyebrow, serif title, the page's actions
// under the description, and a dithered picture of that part of the mill in its own column, so
// buttons never sit on the artwork
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  const pathname = usePathname();
  const crumbs = breadcrumbs(pathname);
  // the nearest menu item, so a detail page wears its section's picture
  const section = [...crumbs].reverse().map((c) => findRoute(c.href)?.nav).find(Boolean);
  const group = section?.group ?? "Setup";
  const { motif, index } = SECTION[group] ?? SECTION.Setup;

  return (
    <header className="relative mb-8 border-t border-foreground">
      <span className="reg -top-[6px] -left-[6px]" aria-hidden />
      <span className="reg -top-[6px] -right-[6px]" aria-hidden />
      <div className="grid gap-6 py-7 sm:grid-cols-[minmax(0,1fr)_minmax(0,42%)]">
        <div className="flex min-w-0 flex-col">
          <p className="eyebrow">
            <span className="num text-foreground">{index}</span>
            <span aria-hidden>·</span>
            {crumbs.length > 1 ? (
              <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2">
                {crumbs.slice(0, -1).map((c, i) => (
                  <Fragment key={c.href}>
                    {i > 0 && <span aria-hidden>/</span>}
                    <Link href={c.href} className="hover:text-ember">
                      {c.title}
                    </Link>
                  </Fragment>
                ))}
              </nav>
            ) : (
              <span>{group}</span>
            )}
          </p>
          <h1 className="mt-3 truncate text-[2.5rem] font-normal sm:text-[3rem]">{title}</h1>
          {description && <p className="mt-2 max-w-xl text-[0.97rem] text-body">{description}</p>}
          {actions && <div className="mt-5 flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
        <DitherPlate
          motif={motif}
          seed={pathname}
          className="pointer-events-none hidden min-h-36 sm:block [mask-image:linear-gradient(to_right,transparent,#000_30%)]"
        />
      </div>
      <div className="h-px bg-border" aria-hidden />
    </header>
  );
}
