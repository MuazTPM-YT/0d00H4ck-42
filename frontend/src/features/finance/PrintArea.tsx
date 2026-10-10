import type { ReactNode } from "react";

// on paper only this block shows: app shell, sidebar and buttons are hidden by the print rule
export function PrintArea({ children }: { children: ReactNode }) {
  return (
    <>
      <style>{`@media print {
        body * { visibility: hidden; }
        #print-area, #print-area * { visibility: visible; }
        #print-area { position: absolute; inset: 0 auto auto 0; width: 100%; border: 0; }
      }`}</style>
      <div id="print-area" className="rounded-lg border bg-card p-6 text-sm">
        {children}
      </div>
    </>
  );
}
