import { AttentionList, BriefingCard } from "@/features/analytics/AttentionList";
import { FloorBoard } from "@/features/production/FloorBoard";

// supervisor home: briefing first, the live board, then the to-do list
export default function Page() {
  return (
    <>
      <FloorBoard top={<BriefingCard />} />
      <div className="mt-8">
        <AttentionList />
      </div>
    </>
  );
}
