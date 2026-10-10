import { Suspense } from "react";

import { Wages } from "@/features/finance/Wages";

export default function Page() {
  return (
    <Suspense>
      <Wages />
    </Suspense>
  );
}
