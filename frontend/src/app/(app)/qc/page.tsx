import { AttentionList } from "@/features/analytics/AttentionList";
import { QcPage } from "@/features/quality/QcPage";

// QC home: the queue, then the rolls that have waited too long
export default function Page() {
  return (
    <>
      <QcPage />
      <div className="mt-8">
        <AttentionList />
      </div>
    </>
  );
}
