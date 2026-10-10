import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

// square ledger buttons: mono caps, 44px tall (minimum touch target); they answer on press-down
const buttonVariants = cva(
  "pressable inline-flex shrink-0 items-center justify-center gap-2 font-mono font-medium uppercase tracking-[0.1em] whitespace-nowrap select-none outline-none disabled:pointer-events-none disabled:opacity-40 aria-invalid:ring-2 aria-invalid:ring-destructive/30 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-[1.15em]",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-ember",
        destructive: "bg-destructive text-white hover:bg-destructive/90",
        outline: "border border-foreground/80 bg-transparent text-foreground hover:border-ember hover:text-ember",
        secondary: "border border-border bg-secondary text-secondary-foreground hover:bg-accent",
        ghost: "text-foreground hover:bg-accent",
        link: "normal-case tracking-normal font-sans text-ember underline-offset-4 hover:underline",
      },
      size: {
        default: "h-11 px-5 text-[0.8rem] has-[>svg]:px-4",
        xs: "h-7 gap-1 px-2.5 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        sm: "h-9 gap-1.5 px-4 text-[0.74rem] has-[>svg]:px-3 pointer-coarse:h-11",
        lg: "h-13 px-7 text-[0.86rem] has-[>svg]:px-6",
        icon: "size-11",
        "icon-xs": "size-7 [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-9 pointer-coarse:size-11",
        "icon-lg": "size-12",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
