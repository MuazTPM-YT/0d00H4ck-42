import { Suspense } from "react";

import { QcHome } from "@/features/quality/QcHome";

export default function Page() {
  return (
    <Suspense>
      <QcHome />
    </Suspense>
  );
}
