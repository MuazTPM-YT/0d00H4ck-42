"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, type SubmitEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { ROLE_LABEL, ROLES, roleHome, useLogin } from "@/lib/auth";

const DEMO_PASSWORD = "demo1234";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  function submit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!e.currentTarget.checkValidity()) return;
    setErrors({});
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
      className="grid gap-4"
    >
      <FormField name="email" label="Email" error={errors.email} required>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "email-error" : undefined}
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
        />
      </FormField>
      {errors.form && (
        <p role="alert" className="text-sm text-danger">
          {errors.form}
        </p>
      )}
      <Button type="submit" disabled={login.isPending}>
        {login.isPending ? "Logging in…" : "Log in"}
      </Button>

      <div className="mt-2 rounded-md bg-muted p-3 text-sm">
        <p className="mb-2 text-muted-foreground">Demo accounts, password {DEMO_PASSWORD}. Tap one to fill the form.</p>
        <div className="flex flex-wrap gap-1.5">
          {ROLES.map((role) => (
            <button
              key={role}
              type="button"
              className="rounded-full border bg-card px-2.5 py-1 text-xs hover:border-primary hover:text-primary"
              onClick={() => {
                setEmail(`${role}@everest.local`);
                setPassword(DEMO_PASSWORD);
                setErrors({});
              }}
            >
              {ROLE_LABEL[role]}
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh md:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
      <section className="weave hidden flex-col justify-end p-10 text-sidebar-foreground md:flex">
        <p className="text-3xl font-semibold tracking-tight text-white">Everest Textile Mills</p>
        <p className="mt-2 max-w-md text-sidebar-muted">
          Every kilo of yarn from the gate to the buyer&apos;s truck. Runs on the mill&apos;s own server, no internet needed.
        </p>
      </section>
      <section className="flex flex-col justify-center px-4 py-10 sm:px-10">
        <h1 className="text-2xl font-semibold tracking-tight">Log in</h1>
        <p className="mb-6 text-sm text-muted-foreground md:hidden">Everest Textile Mills</p>
        <p className="mb-6 hidden text-sm text-muted-foreground md:block">Use your mill email.</p>
        <Suspense>
          <LoginForm />
        </Suspense>
      </section>
    </main>
  );
}
