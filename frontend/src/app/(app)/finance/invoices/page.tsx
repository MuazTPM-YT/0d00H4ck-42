import { Suspense } from "react";

import { Invoices } from "@/features/finance/Invoices";

export default function Page() {
  return (
    <Suspense>
      <Invoices />
    </Suspense>
  );
}
