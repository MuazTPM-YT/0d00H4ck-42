import { Spool } from "lucide-react";

import { cn } from "@/lib/utils";

// the app's mark: a spool of yarn on an ink square, used in the sidebar, top bar and login
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn("grid size-9 shrink-0 place-items-center bg-primary text-primary-foreground", className)} aria-hidden>
      <Spool className="size-[55%]" strokeWidth={2.2} />
    </span>
  );
}
