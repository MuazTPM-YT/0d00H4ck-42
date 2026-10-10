import { Suspense } from "react";

import { Payments } from "@/features/finance/Payments";

export default function Page() {
  return (
    <Suspense>
      <Payments />
    </Suspense>
  );
}
