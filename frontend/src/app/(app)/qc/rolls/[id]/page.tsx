"use client";

import { useParams } from "next/navigation";

import { PageHeader } from "@/components/layout/PageHeader";
import { RollInspection } from "@/features/quality/RollInspection";
import { useSSE } from "@/lib/useSSE";

export default function Page() {
  const { id } = useParams<{ id: string }>();
  useSSE(["quality"]);
  return (
    <>
      <PageHeader title="Roll" description="Where this roll came from, what QC found, and the decision while it waits." />
      <div className="max-w-3xl">
        <RollInspection key={id} id={Number(id)} />
      </div>
    </>
  );
}
