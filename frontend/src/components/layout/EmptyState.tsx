import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// nothing here yet: a big calm icon, one sentence on why, and the action that fixes it
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
    <div className={cn("flex flex-col items-center gap-3 rounded-3xl bg-card px-6 py-14 text-center shadow-card", className)}>
      <span className="mb-1 grid size-16 place-items-center rounded-2xl bg-muted text-muted-foreground" aria-hidden>
        <Icon className="size-8" strokeWidth={1.7} />
      </span>
      <h2 className="text-lg font-semibold">{title}</h2>
      {children && <div className="max-w-md text-[0.94rem] text-muted-foreground">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
