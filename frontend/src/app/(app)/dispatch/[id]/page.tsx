"use client";

import { useParams } from "next/navigation";

import { DispatchLoad } from "@/features/dispatch/DispatchLoad";

export default function Page() {
  const { id } = useParams<{ id: string }>();
  return <DispatchLoad id={id} />;
}
