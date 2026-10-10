"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { acceptsNumericEdit } from "@/lib/validation"
import { DateInput } from "./date-input"
import { TimeInput } from "./time-input"

// 44px square fields: hairline at rest, ember line when focused, red when invalid
function Input({ className, type, onChange, onKeyDown, onPaste, ...props }: React.ComponentProps<"input">) {
  const unsigned = (type === "number" && !(Number(props.min) < 0)) || props.inputMode === "decimal" || props.inputMode === "numeric"
  const integer = props.inputMode === "numeric"
  const accepted = React.useRef(String(props.value ?? props.defaultValue ?? ""))
  React.useEffect(() => {
    if (props.value !== undefined) accepted.current = String(props.value)
  }, [props.value])
  if (type === "date" || type === "month") return <DateInput {...props} type={type} className={className} onChange={onChange} onKeyDown={onKeyDown} onPaste={onPaste} />
  if (type === "time") return <TimeInput {...props} className={className} onChange={onChange} onKeyDown={onKeyDown} onPaste={onPaste} />
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
      onKeyDown={(event) => {
        onKeyDown?.(event)
        if (unsigned && !event.ctrlKey && !event.metaKey && ["-", "+", "e", "E"].includes(event.key)) event.preventDefault()
      }}
      onPaste={(event) => {
        onPaste?.(event)
        if (unsigned && !acceptsNumericEdit(event.clipboardData.getData("text"), integer)) event.preventDefault()
      }}
      onChange={(event) => {
        if (unsigned && !acceptsNumericEdit(event.target.value, integer)) {
          event.target.value = props.value !== undefined ? String(props.value) : accepted.current
          return
        }
        accepted.current = event.target.value
        onChange?.(event)
      }}
    />
  )
}

export { Input }
