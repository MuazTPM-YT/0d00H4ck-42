"use client";

import { Suspense } from "react";

import { InsightsPage } from "@/features/analytics/InsightsPage";

// Suspense: the page reads ?id= from the URL
export default function Page() {
  return (
    <Suspense>
      <InsightsPage />
    </Suspense>
  );
}
