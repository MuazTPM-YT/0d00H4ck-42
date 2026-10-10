"use client";

import {
  CircleAlert,
  ClipboardCheck,
  Factory,
  Gauge,
  IndianRupee,
  type LucideIcon,
  Radio,
  ScanLine,
  Truck,
  Warehouse,
  WifiOff,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, type SubmitEvent, useState } from "react";

import type { MotifName } from "@/components/dither/motifs";
import { BrandMark } from "@/components/layout/BrandMark";
import { GlassInput, GlassInputWrapper, type Highlight, PasswordInput, SignInPage } from "@/components/ui/sign-in";
import { ApiError } from "@/lib/api";
import { type Role, ROLE_LABEL, ROLES, roleHome, useLogin } from "@/lib/auth";
import { cn } from "@/lib/utils";

const DEMO_PASSWORD = "demo1234";

const ROLE_ICON: Record<Role, LucideIcon> = {
  owner: Gauge,
  store: Warehouse,
  supervisor: Factory,
  qc: ClipboardCheck,
  dispatch: Truck,
  accounts: IndianRupee,
};

// tap a role and the print shows that person's part of the mill
const ROLE_ART: Record<Role, { motif: MotifName; caption: string }> = {
  owner: { motif: "mill", caption: "Plate 02 · the whole mill" },
  store: { motif: "cones", caption: "Plate 03 · yarn store" },
  supervisor: { motif: "loom", caption: "Plate 04 · the loom floor" },
  qc: { motif: "loupe", caption: "Plate 05 · quality check" },
  dispatch: { motif: "truck", caption: "Plate 06 · dispatch" },
  accounts: { motif: "orders", caption: "Plate 07 · orders and books" },
};

// what the mill gets, said plainly, on the photo
const HIGHLIGHTS: Highlight[] = [
  { icon: Radio, title: "Live floor board", text: "Every loom's job, output and status, updating as it happens." },
  { icon: ScanLine, title: "Every roll traced", text: "From the yarn lot at the gate to the truck that takes it away." },
  { icon: WifiOff, title: "Runs on your server", text: "No cloud, no internet. Your data stays in the mill." },
];

function FieldError({ id, children }: { id: string; children?: string }) {
  if (!children) return null;
  return (
    <p id={id} role="alert" className="mt-1.5 flex items-center gap-1.5 text-sm font-medium text-danger">
      <CircleAlert className="size-4 shrink-0" aria-hidden />
      {children}
    </p>
  );
}

function LoginForm({ onRole }: { onRole: (role: Role | null) => void }) {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrors({});
    if (!e.currentTarget.checkValidity()) return;
    login.mutate(
      { email, password },
      {
        onSuccess: ({ user }) => router.replace(next?.startsWith("/") && next !== "/login" ? next : roleHome(user.role)),
        onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
      },
    );
  }

  return (
    <>
      <form
        noValidate
        onSubmit={submit}
        onInvalidCapture={(e) => {
          const el = e.target as HTMLInputElement;
          setErrors((prev) => ({ ...prev, [el.name]: el.validationMessage }));
        }}
        className="space-y-5"
      >
        <div className="animate-element animate-delay-300">
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-muted-foreground">Email address</label>
          <GlassInputWrapper invalid={!!errors.email}>
            <GlassInput
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              placeholder="you@everest.local"
              required
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                onRole(ROLES.find((r) => e.target.value === `${r}@everest.local`) ?? null);
              }}
              aria-invalid={!!errors.email}
              aria-describedby={errors.email ? "email-error" : undefined}
            />
          </GlassInputWrapper>
          <FieldError id="email-error">{errors.email}</FieldError>
        </div>

        <div className="animate-element animate-delay-400">
          <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-muted-foreground">Password</label>
          <GlassInputWrapper invalid={!!errors.password}>
            <PasswordInput
              id="password"
              name="password"
              autoComplete="current-password"
              placeholder="Enter your password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? "password-error" : undefined}
            />
          </GlassInputWrapper>
          <FieldError id="password-error">{errors.password}</FieldError>
        </div>

        {errors.form && (
          <p role="alert" className="border border-danger/40 bg-danger-soft px-4 py-3 text-sm font-medium text-danger">{errors.form}</p>
        )}

        <button
          type="submit"
          disabled={login.isPending}
          className="animate-element animate-delay-500 pressable w-full bg-primary py-4 font-mono text-[0.84rem] font-medium tracking-[0.14em] uppercase text-primary-foreground hover:bg-ember disabled:opacity-50"
        >
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="animate-element animate-delay-600 relative flex items-center justify-center">
        <span className="w-full border-t border-foreground" />
        <span className="label absolute bg-background px-4">Demo · tap who you are</span>
      </div>

      <div className="animate-element animate-delay-700 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {ROLES.map((role) => {
          const Icon = ROLE_ICON[role];
          const picked = email === `${role}@everest.local`;
          return (
            <button
              key={role}
              type="button"
              aria-pressed={picked}
              onClick={() => {
                onRole(role);
                setEmail(`${role}@everest.local`);
                setPassword(DEMO_PASSWORD);
                setErrors({});
              }}
              className={cn(
                "pressable inline-flex h-11 min-w-0 items-center gap-2 border px-3 text-left text-sm font-medium",
                picked ? "border-primary bg-primary text-primary-foreground" : "border-input bg-card hover:border-ember hover:text-ember",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="truncate">{ROLE_LABEL[role]}</span>
            </button>
          );
        })}
      </div>

      <p className="animate-element animate-delay-800 text-center text-sm text-muted-foreground">
        Every demo account uses the password <span className="num font-medium text-foreground">{DEMO_PASSWORD}</span>.
      </p>
    </>
  );
}

export default function LoginPage() {
  const [role, setRole] = useState<Role | null>(null);
  return (
    <SignInPage
      heroArt={role ? { ...ROLE_ART[role], key: role } : undefined}
      brand={
        <div className="flex items-center gap-3">
          <BrandMark className="size-10" />
          <span className="leading-tight">
            <span className="block font-display text-2xl leading-none font-medium">Everest</span>
            <span className="label mt-1 block">Textile Mills</span>
          </span>
        </div>
      }
      title={<span className="font-light text-foreground">Welcome <em className="text-ember">back</em></span>}
      description="Sign in to run the mill: yarn, floor, quality, dispatch and books in one place."
      heroImageSrc="/login-fabric.jpg"
      highlights={HIGHLIGHTS}
    >
      <Suspense>
        <LoginForm onRole={setRole} />
      </Suspense>
    </SignInPage>
  );
}
