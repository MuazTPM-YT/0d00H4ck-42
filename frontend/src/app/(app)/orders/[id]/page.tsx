"use client";

import { useParams } from "next/navigation";

import { OrderCostPanel } from "@/features/finance/OrderCostPanel";
import { OrderYarnPanel } from "@/features/orders/OrderYarnPanel";
import { OrderDetail } from "@/features/tracking/OrderDetail";
import { useMe } from "@/lib/auth";

export default function Page() {
  const { id } = useParams<{ id: string }>();
  const role = useMe().data?.role;
  // cost is for the owner's eyes (and accounts); sales sees stage, rolls and invoices only
  const showCost = role === "owner" || role === "accounts";
  return (
    <OrderDetail
      id={id}
      yarnPanel={<OrderYarnPanel orderId={Number(id)} />}
      costPanel={showCost && <OrderCostPanel orderId={id} />}
    />
  );
}
