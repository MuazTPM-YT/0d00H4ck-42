"use client";

import * as React from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import { Select as SelectPrimitive } from "radix-ui";
import { cn } from "@/lib/utils";

type Choice = { value: string; label: string; disabled: boolean; group: string };
const EMPTY = "__everest_empty_option__";

// Native form semantics stay intact; Radix owns the themed, keyboard-accessible menu.
export function Select({ children, className, id, onKeyDown, ...props }: React.ComponentProps<"select">) {
  const native = React.useRef<HTMLSelectElement>(null);
  const trigger = React.useRef<HTMLButtonElement>(null);
  const [choices, setChoices] = React.useState<Choice[]>([]);
  const [selected, setSelected] = React.useState(String(props.value ?? props.defaultValue ?? ""));
  const [invalid, setInvalid] = React.useState(false);

  // Read real options, including options rendered by grouped worker/machine components.
  React.useLayoutEffect(() => {
    if (!native.current) return;
    const next = Array.from(native.current.options).map((option) => ({
      value: option.value,
      label: option.textContent?.trim() ?? "",
      disabled: option.disabled || (option.parentElement instanceof HTMLOptGroupElement && option.parentElement.disabled),
      group: option.parentElement instanceof HTMLOptGroupElement ? option.parentElement.label : "",
    }));
    setChoices((old) => JSON.stringify(old) === JSON.stringify(next) ? old : next);
    setSelected(native.current.value);
  }, [children, props.value, props.defaultValue]);

  React.useEffect(() => {
    const form = native.current?.form;
    const reset = () => requestAnimationFrame(() => { setSelected(native.current?.value ?? ""); setInvalid(false); });
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, []);

  function choose(value: string) {
    const next = value === EMPTY ? "" : value;
    const el = native.current;
    if (!el) return;
    el.value = next;
    setSelected(next);
    setInvalid(false);
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  const choice = choices.find((item) => item.value === selected);
  return (
    <>
      <select {...props} ref={native} aria-hidden="true" tabIndex={-1} className="sr-only" onInvalid={(event) => {
        props.onInvalid?.(event);
        event.preventDefault();
        setInvalid(true);
        trigger.current?.focus();
      }}>{children}</select>
      <SelectPrimitive.Root value={selected || EMPTY} onValueChange={choose} disabled={props.disabled}>
        <SelectPrimitive.Trigger
          ref={trigger} id={id} title={choice?.label || props.title}
          aria-label={props["aria-label"]} aria-labelledby={props["aria-labelledby"]}
          aria-describedby={props["aria-describedby"]} aria-required={props.required}
          aria-invalid={props["aria-invalid"] || invalid}
          onKeyDown={(event) => {
            if (!["Enter", " ", "ArrowUp", "ArrowDown"].includes(event.key)) onKeyDown?.(event as unknown as React.KeyboardEvent<HTMLSelectElement>);
          }}
          className={cn("flex min-h-11 min-w-0 w-full max-w-full items-center justify-between gap-2 border border-input bg-card px-3 py-2 text-left font-sans text-base text-foreground outline-none focus-visible:border-ember focus-visible:ring-1 focus-visible:ring-ember disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive", className)}
        >
          <SelectPrimitive.Value asChild><span className="min-w-0 flex-1 truncate">{choice?.label ?? "Choose…"}</span></SelectPrimitive.Value>
          <SelectPrimitive.Icon asChild><ChevronDown className="size-4 shrink-0 text-muted-foreground" /></SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content position="popper" sideOffset={4} collisionPadding={8}
            className="z-[80] max-h-[min(24rem,var(--radix-select-content-available-height))] w-[var(--radix-select-trigger-width)] min-w-40 max-w-[calc(100vw-1rem)] overflow-hidden border border-foreground bg-popover font-sans text-base text-popover-foreground">
            <SelectPrimitive.ScrollUpButton className="grid h-8 place-items-center border-b bg-muted"><ChevronUp className="size-4" /></SelectPrimitive.ScrollUpButton>
            <SelectPrimitive.Viewport className="p-1">
              {choices.map((item, index) => (
                <React.Fragment key={`${item.value}-${index}`}>
                  {item.group && item.group !== choices[index - 1]?.group && <div className="px-3 pt-3 pb-1 text-sm font-semibold text-muted-foreground">{item.group}</div>}
                  <SelectPrimitive.Item value={item.value || EMPTY} disabled={item.disabled} textValue={item.label}
                    className="relative flex min-h-11 cursor-default items-center py-2 pr-9 pl-3 outline-none select-none data-[highlighted]:bg-primary data-[highlighted]:text-primary-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-40">
                    <SelectPrimitive.ItemText><span className="whitespace-normal [overflow-wrap:anywhere]">{item.label}</span></SelectPrimitive.ItemText>
                    <SelectPrimitive.ItemIndicator className="absolute right-3"><Check className="size-4" /></SelectPrimitive.ItemIndicator>
                  </SelectPrimitive.Item>
                </React.Fragment>
              ))}
            </SelectPrimitive.Viewport>
            <SelectPrimitive.ScrollDownButton className="grid h-8 place-items-center border-t bg-muted"><ChevronDown className="size-4" /></SelectPrimitive.ScrollDownButton>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
    </>
  );
}
