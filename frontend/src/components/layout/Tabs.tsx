import { cn } from "@/lib/utils";

export type TabItem<K extends string> = { key: K; label: string; count?: number };

// ledger tabs: a hairline under the row, an ink bar under the open one
export function Tabs<K extends string>({ items, value, onChange, label, className }: { items: TabItem<K>[]; value: K; onChange: (key: K) => void; label: string; className?: string }) {
  return (
    <div role="tablist" aria-label={label} className={cn("mb-5 flex gap-1 overflow-x-auto border-b border-border", className)}>
      {items.map((t) => {
        const on = t.key === value;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.key)}
            className={cn(
              "pressable relative flex h-11 shrink-0 items-center gap-2 px-4 text-[0.94rem] font-medium whitespace-nowrap",
              on ? "text-foreground after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
            {t.count !== undefined && <span className={cn("num border px-1.5 text-[0.72rem]", on ? "border-foreground" : "border-border")}>{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
