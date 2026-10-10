"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

export type Topic = "stock" | "machines" | "orders" | "quality" | "dispatch" | "insights";

// live updates: server says "topic changed", we refetch every query whose key starts with it.
// Rule: query keys start with their topic, e.g. ["machines", "board"], ["stock", itemId].
export function useSSE(topics: Topic[]) {
  const qc = useQueryClient();
  const key = [...topics].sort().join(",");

  useEffect(() => {
    if (!key) return;
    const source = new EventSource(`/api/stream?topics=${key}`);
    source.onmessage = (event) => {
      const { topic } = JSON.parse(event.data) as { topic: Topic };
      qc.invalidateQueries({ queryKey: [topic] });
    };
    return () => source.close();
  }, [key, qc]);
}
