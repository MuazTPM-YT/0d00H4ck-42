"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Truck } from "lucide-react";
import { useParams } from "next/navigation";

import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { Deliveries, StageCard, Timeline, type Track } from "@/features/tracking/StageCard";

// public buyer tracking page: no login, no app shell, no money. Owner: Ashil (tracking).
export default function TrackPage() {
  const { token } = useParams<{ token: string }>();
  const track = useQuery({
    queryKey: ["track", token],
    queryFn: () => api<Track>(`/track/${encodeURIComponent(token)}`),
    refetchInterval: 60_000,
  });

  return (
    <main className="mx-auto grid min-h-dvh max-w-3xl content-start gap-4 p-4 sm:p-8">
      <header className="flex items-center gap-2 text-lg font-semibold">
        <Truck className="size-5" aria-hidden /> Everest Textile Mills · order tracking
      </header>
      {track.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : track.isError ? (
        <EmptyState icon={AlertTriangle} title={track.error.message}>
          The link may have been replaced. Ask your contact at the mill for a new one.
        </EmptyState>
      ) : (
        <>
          <StageCard t={track.data} />
          <Deliveries items={track.data.deliveries ?? []} />
          <Timeline events={track.data.timeline} />
          <p className="text-xs text-muted-foreground">Updates every minute. Times in IST.</p>
        </>
      )}
    </main>
  );
}
