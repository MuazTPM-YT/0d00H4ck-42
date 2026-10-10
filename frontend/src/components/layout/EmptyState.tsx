import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { DitherPlate } from "@/components/dither/DitherPlate";
import { cn } from "@/lib/utils";

// nothing here yet: a dithered spool with its thread loose, one sentence on why, and the fix
export function EmptyState({
  icon: Icon = Inbox,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-3 border border-border bg-card px-6 py-12 text-center", className)}>
      <div className="relative mb-1 h-24 w-40" aria-hidden>
        <DitherPlate motif="spool" seed={title} />
        <Icon className="absolute right-1 bottom-1 size-5 text-ember" strokeWidth={1.8} />
      </div>
      <h2 className="text-[1.6rem] font-normal">{title}</h2>
      {children && <div className="max-w-md text-[0.94rem] text-body">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
