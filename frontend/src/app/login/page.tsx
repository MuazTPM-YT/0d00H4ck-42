"use client";

import {
  ClipboardCheck,
  Factory,
  Gauge,
  IndianRupee,
  type LucideIcon,
  ShoppingCart,
  Truck,
  Warehouse,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, type SubmitEvent, useState } from "react";

import { BrandMark } from "@/components/layout/BrandMark";
import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { type Role, ROLE_LABEL, ROLES, roleHome, useLogin } from "@/lib/auth";
import { cn } from "@/lib/utils";

const DEMO_PASSWORD = "demo1234";

// what each person does, in their words, so the right tile is obvious at a glance
const ROLE_HINT: Record<Role, { icon: LucideIcon; does: string }> = {
  owner: { icon: Gauge, does: "See the whole mill" },
  store: { icon: Warehouse, does: "Receive and issue yarn" },
  supervisor: { icon: Factory, does: "Run the floor" },
  qc: { icon: ClipboardCheck, does: "Check rolls" },
  dispatch: { icon: Truck, does: "Load and ship" },
  accounts: { icon: IndianRupee, does: "Invoices and wages" },
  sales: { icon: ShoppingCart, does: "Take orders" },
};

function LoginForm() {
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
    <form
      noValidate
      onSubmit={submit}
      onInvalidCapture={(e) => {
        const el = e.target as HTMLInputElement;
        setErrors((prev) => ({ ...prev, [el.name]: el.validationMessage }));
      }}
      className="grid gap-5"
    >
      <FormField name="email" label="Email" error={errors.email} required>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          placeholder="you@everest.local"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "email-error" : undefined}
          className="h-12"
        />
      </FormField>
      <FormField name="password" label="Password" error={errors.password} required>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-invalid={!!errors.password}
          aria-describedby={errors.password ? "password-error" : undefined}
          className="h-12"
        />
      </FormField>
      {errors.form && (
        <p role="alert" className="rounded-xl bg-danger-soft px-3.5 py-2.5 text-[0.9rem] font-medium text-danger">
          {errors.form}
        </p>
      )}
      <Button type="submit" size="lg" className="mt-1 w-full" disabled={login.isPending}>
        {login.isPending ? "Signing in…" : "Sign in"}
      </Button>

      <div className="mt-4">
        <div className="mb-3 flex items-center gap-3 text-[0.82rem] text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          Demo: pick who you are
          <span className="h-px flex-1 bg-border" />
        </div>
        <div className="grid grid-cols-1 gap-2 min-[400px]:grid-cols-2">
          {ROLES.map((role) => {
            const { icon: Icon, does } = ROLE_HINT[role];
            const picked = email === `${role}@everest.local`;
            return (
              <button
                key={role}
                type="button"
                aria-pressed={picked}
                className={cn(
                  "pressable flex min-h-14 items-center gap-3 rounded-2xl border bg-card px-3 py-2.5 text-left",
                  picked ? "border-primary ring-2 ring-primary/15" : "border-border hover:border-input",
                )}
                onClick={() => {
                  setEmail(`${role}@everest.local`);
                  setPassword(DEMO_PASSWORD);
                  setErrors({});
                }}
              >
                <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", picked ? "bg-primary text-primary-foreground" : "bg-muted text-foreground")} aria-hidden>
                  <Icon className="size-[1.15rem]" strokeWidth={1.9} />
                </span>
                <span className="min-w-0 leading-tight">
                  <span className="block truncate text-[0.88rem] font-semibold">{ROLE_LABEL[role]}</span>
                  <span className="block truncate text-[0.75rem] text-muted-foreground">{does}</span>
                </span>
              </button>
            );
          })}
        </div>
        <p className="mt-3 text-center text-[0.78rem] text-muted-foreground">
          Every demo account uses the password {DEMO_PASSWORD}.
        </p>
      </div>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-4 py-8">
      {/* soft light from above, like a product shot; purely decorative */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-[28rem] max-w-3xl rounded-full bg-[radial-gradient(closest-side,var(--card),transparent)] opacity-90"
      />
      <section className="page-in relative w-full max-w-md">
        <div className="mb-6 flex flex-col items-center text-center">
          <BrandMark className="mb-4 size-14 rounded-2xl" />
          <h1 className="text-[2rem] font-bold">Sign in to Everest</h1>
          <p className="mt-2 text-[0.97rem] text-muted-foreground">
            Yarn to dispatch, on the mill&apos;s own server. No internet needed.
          </p>
        </div>
        <div className="rounded-3xl bg-card p-6 shadow-raised sm:p-8">
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
