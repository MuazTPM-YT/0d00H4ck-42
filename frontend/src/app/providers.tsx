"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { TourProvider } from "@/features/tour/Tour";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            // 4xx will not fix itself; only retry network and server errors
            retry: (count, err) => count < 2 && !(err instanceof ApiError && err.status >= 400 && err.status < 500),
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <TourProvider>{children}</TourProvider>
    </QueryClientProvider>
  );
}
