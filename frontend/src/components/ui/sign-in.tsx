"use client";

import { Eye, EyeOff, type LucideIcon } from "lucide-react";
import { type ComponentProps, type ReactNode, useState } from "react";

import { cn } from "@/lib/utils";

// split sign-in screen: form on the left, a hero photo with glass cards on the right
// (adapted from a 21st.dev component; images are local so it works offline)

export type Highlight = { icon: LucideIcon; title: string; text: string };

// soft glass field: tinted fill, brightens when focused
export function GlassInputWrapper({ children, invalid }: { children: ReactNode; invalid?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-2xl border bg-foreground/[0.035] backdrop-blur-sm transition-[border-color,background-color,box-shadow] duration-150",
        "focus-within:border-foreground/40 focus-within:bg-card focus-within:shadow-[0_0_0_4px_rgb(0_0_0/0.05)]",
        invalid ? "border-danger/70 bg-danger-soft/40" : "border-border",
      )}
    >
      {children}
    </div>
  );
}

export function GlassInput({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn("w-full rounded-2xl bg-transparent p-4 text-[0.97rem] placeholder:text-muted-foreground/70 focus:outline-none", className)} {...props} />;
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
        className="pressable absolute inset-y-0 right-2 my-auto grid size-10 place-items-center rounded-full text-muted-foreground hover:text-foreground"
      >
        {show ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
      </button>
    </div>
  );
}

function HighlightCard({ item, delay }: { item: Highlight; delay: string }) {
  const Icon = item.icon;
  return (
    <div className={cn("animate-testimonial flex w-64 items-start gap-3 rounded-3xl border border-white/40 bg-white/55 p-5 shadow-raised backdrop-blur-xl", delay)}>
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-primary text-primary-foreground" aria-hidden>
        <Icon className="size-5" />
      </span>
      <div className="text-sm leading-snug">
        <p className="font-semibold text-foreground">{item.title}</p>
        <p className="mt-1 text-foreground/75">{item.text}</p>
      </div>
    </div>
  );
}

export function SignInPage({
  brand,
  title,
  description,
  heroImageSrc,
  highlights = [],
  children,
}: {
  brand?: ReactNode;
  title: ReactNode;
  description: ReactNode;
  heroImageSrc?: string;
  highlights?: Highlight[];
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-dvh w-full flex-col bg-background md:flex-row">
      <section className="flex flex-1 items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="flex flex-col gap-6">
            {brand && <div className="animate-element animate-delay-100">{brand}</div>}
            <h1 className="animate-element animate-delay-100 text-4xl leading-tight font-semibold md:text-5xl">{title}</h1>
            <p className="animate-element animate-delay-200 text-[1.02rem] text-muted-foreground">{description}</p>
            {children}
          </div>
        </div>
      </section>

      {heroImageSrc && (
        <section className="relative hidden flex-1 p-4 md:block">
          <div className="animate-slide-right animate-delay-300 absolute inset-4 overflow-hidden rounded-3xl bg-cover bg-center" style={{ backgroundImage: `url(${heroImageSrc})` }}>
            <div className="absolute inset-0 bg-gradient-to-t from-black/25 via-transparent to-transparent" aria-hidden />
          </div>
          {highlights.length > 0 && (
            <div className="absolute bottom-8 left-1/2 flex w-full -translate-x-1/2 justify-center gap-4 px-8">
              <HighlightCard item={highlights[0]} delay="animate-delay-1000" />
              {highlights[1] && <div className="hidden xl:flex"><HighlightCard item={highlights[1]} delay="animate-delay-1200" /></div>}
              {highlights[2] && <div className="hidden 2xl:flex"><HighlightCard item={highlights[2]} delay="animate-delay-1400" /></div>}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
