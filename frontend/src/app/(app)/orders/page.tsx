import { AttentionList } from "@/features/analytics/AttentionList";
import { OrderList } from "@/features/orders/OrderList";

// sales home: orders, then the hand-offs waiting on the desk
export default function Page() {
  return (
    <>
      <OrderList />
      <div className="mt-8">
        <AttentionList />
      </div>
    </>
  );
}
