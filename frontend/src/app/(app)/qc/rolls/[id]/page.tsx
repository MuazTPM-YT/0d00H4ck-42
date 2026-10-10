"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";

import { RollPage } from "@/features/quality/RollPage";

export default function Page() {
  const { id } = useParams<{ id: string }>();
  return (
    <Suspense>
      <RollPage key={id} id={Number(id)} />
    </Suspense>
  );
}
