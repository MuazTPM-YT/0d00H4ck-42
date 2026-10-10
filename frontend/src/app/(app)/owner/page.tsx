"use client";

import { Lightbulb } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { AttentionList, BriefingCard } from "@/features/analytics/AttentionList";
import { DeliveryBoard } from "@/features/analytics/Delivery";
import { useSSE } from "@/lib/useSSE";

export default function Page() {
  useSSE(["insights", "orders"]);
  return (
    <>
      <PageHeader
        title="Overview"
        description="What needs you, and when each order will really ship"
        actions={
          <Button asChild>
            <Link href="/insights">
              <Lightbulb /> All insights
            </Link>
          </Button>
        }
      />
      <BriefingCard />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <AttentionList />
        <section aria-labelledby="delivery-title" className="grid content-start gap-3">
          <h2 id="delivery-title" className="text-base font-semibold">
            Delivery forecast
          </h2>
          <DeliveryBoard />
        </section>
      </div>
    </>
  );
}
