import { AttentionList } from "@/features/analytics/AttentionList";
import { StoreHome } from "@/features/inventory/StoreHome";

// store home: the yarn desk, then the hand-offs waiting on the store
export default function Page() {
  return (
    <>
      <StoreHome />
      <div className="mt-8">
        <AttentionList />
      </div>
    </>
  );
}
