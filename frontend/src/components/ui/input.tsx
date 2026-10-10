import * as React from "react"
import { cn } from "@/lib/utils"

// 44px fields with a soft focus halo; red border + halo when the field is invalid
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-11 w-full min-w-0 rounded-xl border border-input bg-card px-3.5 py-1 text-base shadow-xs outline-none placeholder:text-muted-foreground/70 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "transition-[border-color,box-shadow] duration-150 ease-out",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
        "focus-visible:border-ring focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/15",
        "aria-invalid:border-destructive aria-invalid:ring-4 aria-invalid:ring-destructive/12",
        className
      )}
      {...props}
    />
  )
}

export { Input }
