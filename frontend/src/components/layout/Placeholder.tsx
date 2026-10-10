"use client";

import { Hammer } from "lucide-react";
import { usePathname } from "next/navigation";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { findRoute } from "@/nav";

// stand-in for a screen its owner has not built yet
export function Placeholder() {
  const route = findRoute(usePathname());
  return (
    <>
      <PageHeader title={route?.title ?? "Screen"} />
      <EmptyState icon={Hammer} title="This screen is being built">
        {route && `Part of the ${route.module} module, owned by ${route.owner}.`}
      </EmptyState>
    </>
  );
}
