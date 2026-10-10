"use client";

import { Eye, EyeOff, type LucideIcon } from "lucide-react";
import { type ComponentProps, type ReactNode, useState } from "react";

import { DitherImage } from "@/components/dither/DitherImage";
import { DitherPlate } from "@/components/dither/DitherPlate";
import type { MotifName } from "@/components/dither/motifs";
import { cn } from "@/lib/utils";

// split sign-in screen: form on the left, the cloth printed in Bayer dots on the right with a
// ledger of what the mill gets (adapted from a 21st.dev component; the photo is local, offline)

export type Highlight = { icon: LucideIcon; title: string; text: string };

// square hairline field: paper fill, ember line when focused
export function GlassInputWrapper({ children, invalid }: { children: ReactNode; invalid?: boolean }) {
  return (
    <div
      className={cn(
        "border bg-card transition-[border-color,box-shadow] duration-150",
        "focus-within:border-ember focus-within:shadow-[0_0_0_1px_var(--ember)]",
        invalid ? "border-danger bg-danger-soft/40" : "border-input",
      )}
    >
      {children}
    </div>
  );
}

export function GlassInput({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn("w-full bg-transparent p-4 text-[0.97rem] placeholder:text-muted-foreground/70 focus:outline-none", className)} {...props} />;
}

export function PasswordInput(props: ComponentProps<"input">) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <GlassInput {...props} type={show ? "text" : "password"} className="pr-12" />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
        className="pressable absolute inset-y-0 right-2 my-auto grid size-10 place-items-center text-muted-foreground hover:text-foreground"
      >
        {show ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
      </button>
    </div>
  );
}

// one ledger row on the print: index, what the mill gets, one line on it
function HighlightRow({ item, n }: { item: Highlight; n: number }) {
  const Icon = item.icon;
  return (
    <li className="grid grid-cols-[2.5rem_1fr_auto] items-start gap-3 border-t border-border py-3.5 first:border-foreground">
      <span className="num pt-0.5 text-[0.78rem] text-ember">{String(n).padStart(2, "0")}</span>
      <div className="leading-snug">
        <p className="font-medium text-foreground">{item.title}</p>
        <p className="mt-0.5 text-sm text-body">{item.text}</p>
      </div>
      <Icon className="mt-0.5 size-5 text-muted-foreground" aria-hidden />
    </li>
  );
}

export function SignInPage({
  brand,
  title,
  description,
  heroImageSrc,
  heroArt,
  highlights = [],
  children,
}: {
  brand?: ReactNode;
  title: ReactNode;
  description: ReactNode;
  heroImageSrc?: string;
  /** a role was picked: print that part of the mill instead of the cloth */
  heroArt?: { motif: MotifName; caption: string; key: string };
  highlights?: Highlight[];
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-dvh w-full flex-col bg-background md:flex-row">
      <section className="flex flex-1 items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="flex flex-col gap-6">
            {brand && <div className="animate-element animate-delay-100">{brand}</div>}
            <p className="eyebrow animate-element animate-delay-100">Sign in</p>
            <h1 className="animate-element animate-delay-100 -mt-2 text-5xl leading-none md:text-6xl">{title}</h1>
            <p className="animate-element animate-delay-200 text-[1.02rem] text-body">{description}</p>
            {children}
          </div>
        </div>
      </section>

      {heroImageSrc && (
        <section className="relative hidden flex-1 flex-col border-l border-foreground p-8 md:flex">
          <span className="reg -top-[6px] -left-[6px]" aria-hidden />
          <div className="animate-slide-right animate-delay-300 relative min-h-0 flex-1 border border-border">
            {heroArt ? (
              <DitherPlate key={heroArt.key} motif={heroArt.motif} seed={heroArt.key} className="plate-in absolute inset-x-0 top-0 !h-[72%]" label={heroArt.caption} />
            ) : (
              <DitherImage src={heroImageSrc} className="absolute inset-0" label="Cloth on the loom, printed in dots" />
            )}
            {/* Everest stands over every print: the mill's name, in dots */}
            <DitherPlate motif="everest" seed="everest" className="pointer-events-none absolute inset-x-0 bottom-0 !h-[46%]" label="Mount Everest" />
            <p className="label absolute top-3 left-3 bg-background px-2 py-1">{heroArt ? heroArt.caption : "Plate 01 · warp and weft"}</p>
            <p className="label absolute right-3 bottom-3 bg-background px-2 py-1">8,849 m · 27.98° N 86.92° E</p>
          </div>
          {highlights.length > 0 && (
            <ul className="animate-testimonial animate-delay-1000 mt-6">
              {highlights.map((h, i) => (
                <HighlightRow key={h.title} item={h} n={i + 1} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
