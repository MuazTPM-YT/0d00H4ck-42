"use client";

import { Lightbulb } from "lucide-react";
import Link from "next/link";

import { DitherBand } from "@/components/dither/DitherBand";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { AttentionList, BriefingCard } from "@/features/analytics/AttentionList";
import { OwnerDashboard } from "@/features/analytics/OwnerDashboard";
import { DeliveryBoard } from "@/features/analytics/Delivery";
import { useSSE } from "@/lib/useSSE";

export default function Page() {
  useSSE(["insights", "orders", "machines"]);
  return (
    <>
      <PageHeader
        title="Overview"
        description="Money, fabric, machines and deliveries at a glance"
        actions={
          <Button asChild>
            <Link href="/insights">
              <Lightbulb /> All insights
            </Link>
          </Button>
        }
      />
      <BriefingCard />
      <OwnerDashboard />
      <DitherBand className="my-8" direction="center" />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <AttentionList />
        <section aria-labelledby="delivery-title" className="grid min-w-0 content-start gap-3">
          <h2 id="delivery-title" className="text-base font-semibold">
            Delivery forecast
          </h2>
          <DeliveryBoard />
        </section>
      </div>
    </>
  );
}
