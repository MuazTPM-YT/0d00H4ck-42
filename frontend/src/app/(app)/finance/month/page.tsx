import { Suspense } from "react";

import { Month } from "@/features/finance/Month";

export default function Page() {
  return (
    <Suspense>
      <Month />
    </Suspense>
  );
}
