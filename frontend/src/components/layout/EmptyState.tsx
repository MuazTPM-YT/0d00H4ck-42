import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

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
    <div className={cn("flex flex-col items-center gap-3 rounded-lg border border-dashed bg-card px-6 py-12 text-center", className)}>
      <Icon className="size-8 text-muted-foreground" aria-hidden />
      <h2 className="text-base font-semibold">{title}</h2>
      {children && <div className="max-w-prose text-sm text-muted-foreground">{children}</div>}
      {action}
    </div>
  );
}
