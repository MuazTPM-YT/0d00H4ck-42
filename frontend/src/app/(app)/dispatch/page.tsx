import { AttentionList } from "@/features/analytics/AttentionList";
import { DispatchList } from "@/features/dispatch/DispatchList";

// dispatch home: trucks, then the ones waiting on this desk
export default function Page() {
  return (
    <>
      <DispatchList />
      <div className="mt-8">
        <AttentionList />
      </div>
    </>
  );
}
