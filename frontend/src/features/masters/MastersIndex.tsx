"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";

import { PageHeader } from "@/components/layout/PageHeader";
import { api, type Paged } from "@/lib/api";

import { MASTERS } from "./config";

const ALL = [...MASTERS.map((m) => ({ path: m.path, title: m.title, description: m.description })),
  { path: "fabric-types", title: "Fabric types", description: "Width, GSM, loss, route and yarn recipe for each fabric." }];

// one card per master with its live record count
export function MastersIndex() {
  const counts = useQueries({
    queries: ALL.map((m) => ({
      queryKey: ["masters", m.path, "count"],
      queryFn: () => api<Paged<unknown>>(`/masters/${m.path}?limit=1`),
    })),
  });

  return (
    <>
      <PageHeader title="Masters" description="The fixed lists every other screen reads from." />
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {ALL.map((m, i) => (
          <li key={m.path}>
            <Link href={`/masters/${m.path}`} className="flex h-full flex-col gap-1 lift rounded-2xl border border-border/60 bg-card p-5 shadow-card focus-visible:outline-2 focus-visible:outline-ring">
              <span className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{m.title}</span>
                <span className="text-sm text-muted-foreground tabular">{counts[i].data?.total ?? "…"}</span>
              </span>
              <span className="text-sm text-muted-foreground">{m.description}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
