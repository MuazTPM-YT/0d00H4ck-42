import { Truck } from "lucide-react";

import { EmptyState } from "@/components/layout/EmptyState";

// public buyer tracking page: no login, no app shell. Owner: Ashil (tracking).
export default function TrackPage() {
  return (
    <main className="mx-auto grid min-h-dvh max-w-xl place-items-center p-4">
      <EmptyState icon={Truck} title="Order tracking is being built">
        Buyers will see their order stage here without logging in.
      </EmptyState>
    </main>
  );
}
