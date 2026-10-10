"use client";

import { useParams } from "next/navigation";

import { OrderDetail } from "@/features/tracking/OrderDetail";

export default function Page() {
  const { id } = useParams<{ id: string }>();
  return <OrderDetail id={id} />;
}
