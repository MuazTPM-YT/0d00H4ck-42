import * as React from "react"
import { cn } from "@/lib/utils"

// 44px square fields: hairline at rest, ember line when focused, red when invalid
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-11 w-full min-w-0 border border-input bg-card px-3.5 py-1 text-base outline-none placeholder:text-muted-foreground/70 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "transition-[border-color,box-shadow] duration-150 ease-out",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
        "focus-visible:border-ember focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ember",
        "aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive",
        className
      )}
      {...props}
    />
  )
}

export { Input }
