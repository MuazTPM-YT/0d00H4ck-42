"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Truck } from "lucide-react";
import { useParams } from "next/navigation";

import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { dateTime, metres } from "@/lib/format";
import { CodeForm, type DeliverBody } from "@/features/dispatch/CodeForm";

// same shape as DeliveryOut in backend/app/modules/dispatch/schemas.py
type Delivery = {
  challan: string;
  order_code: string;
  buyer_name: string;
  buyer_city: string | null;
  fabric: string;
  colour: string;
  vehicle_no: string | null;
  driver: string | null;
  left_at: string;
  rolls: { code: string; length_m: string }[];
  roll_count: number;
  metres: string;
  delivered_at: string | null;
  received_by: string | null;
  delivery_note: string | null;
  tries_left: number;
  has_code: boolean;
};

// public driver page: no login, no money. The buyer's code closes the trip. Owner: Ashil (dispatch).
export default function DeliverPage() {
  const { token } = useParams<{ token: string }>();
  const qc = useQueryClient();
  const key = ["deliver", token];
  const trip = useQuery({ queryKey: key, queryFn: () => api<Delivery>(`/deliver/${encodeURIComponent(token)}`) });
  const deliver = useMutation({
    mutationFn: (body: DeliverBody) => api<Delivery>(`/deliver/${encodeURIComponent(token)}`, { method: "POST", json: body }),
    onSuccess: (d) => qc.setQueryData(key, d),
    // a wrong code spends a try: reload so the count and the lock show
    onError: () => qc.invalidateQueries({ queryKey: key }),
  });

  return (
    <main className="mx-auto grid min-h-dvh max-w-xl content-start gap-4 p-4 sm:p-8">
      <header className="flex items-center gap-2 text-lg font-semibold">
        <Truck className="size-5" aria-hidden /> Everest Textile Mills · delivery
      </header>
      {trip.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : trip.isError ? (
        <EmptyState icon={AlertTriangle} title={trip.error.message}>
          Check the link from the mill office. It opens only after the truck has left the mill.
        </EmptyState>
      ) : (
        <>
          <section className="grid gap-1 rounded-lg border bg-card p-4 text-sm">
            <div className="text-base font-medium">Challan {trip.data.challan}</div>
            <div>
              To <strong>{trip.data.buyer_name}</strong>
              {trip.data.buyer_city && `, ${trip.data.buyer_city}`}
            </div>
            <div className="text-muted-foreground">
              Order {trip.data.order_code} · {trip.data.fabric}, {trip.data.colour}
            </div>
            <div className="text-muted-foreground">
              {trip.data.vehicle_no}
              {trip.data.driver && ` · ${trip.data.driver}`} · left {dateTime(trip.data.left_at)}
            </div>
          </section>

          <section className="rounded-lg border bg-card">
            <h2 className="border-b px-4 py-3 font-medium">
              Count these rolls with the buyer ({trip.data.roll_count} · {metres(trip.data.metres)})
            </h2>
            <ul className="divide-y text-sm">
              {trip.data.rolls.map((r, i) => (
                <li key={r.code} className="flex items-center gap-3 px-4 py-2">
                  <span className="w-6 text-muted-foreground tabular">{i + 1}</span>
                  <span className="flex-1 font-medium">{r.code}</span>
                  <span className="tabular">{metres(r.length_m)}</span>
                </li>
              ))}
            </ul>
          </section>

          {trip.data.delivered_at ? (
            <section className="grid gap-1 rounded-lg border border-success bg-success-soft p-4 text-success">
              <div className="flex items-center gap-2 text-base font-medium">
                <CheckCircle2 className="size-5" aria-hidden /> Delivered {dateTime(trip.data.delivered_at)}
              </div>
              <div>Received by {trip.data.received_by}</div>
              {trip.data.delivery_note && <div>Note: {trip.data.delivery_note}</div>}
            </section>
          ) : !trip.data.has_code || trip.data.tries_left === 0 ? (
            <section role="alert" className="grid gap-3 rounded-lg border bg-warning-soft p-4 text-warning">
              <p>
                {trip.data.has_code
                  ? "Too many wrong codes. Call the mill office: they will send the buyer a new code."
                  : "This truck has no delivery code yet. Call the mill office."}
              </p>
              <Button variant="outline" onClick={() => trip.refetch()} disabled={trip.isFetching}>
                Check again
              </Button>
            </section>
          ) : (
            <section className="grid gap-3 rounded-lg border bg-card p-4">
              <h2 className="font-medium">Hand over</h2>
              <p className="text-sm text-muted-foreground">
                Once the buyer has counted the rolls, ask them for the delivery code on their order link.
                {trip.data.tries_left < 5 && ` ${trip.data.tries_left} ${trip.data.tries_left === 1 ? "try" : "tries"} left.`}
              </p>
              <CodeForm label="Mark delivered" onSubmit={(b) => deliver.mutate(b)} pending={deliver.isPending} error={deliver.error} />
            </section>
          )}
        </>
      )}
    </main>
  );
}
