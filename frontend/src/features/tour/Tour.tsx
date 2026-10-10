"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, ChevronDown, Compass, LoaderCircle, LogIn, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useMotion } from "@/components/dither/ticker";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { DEMO_PASSWORD, demoEmail, ROLE_LABEL, type Role, useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { type Step, STEPS, type TourState } from "./steps";

const KEY = "everest.tour";
// buyer and driver pages are for outsiders: no tour on them
const OUTSIDE = ["/track/", "/deliver/"];

function load(): TourState | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as TourState) : null;
  } catch {
    return null;
  }
}

function store(s: TourState | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {}
}

const TourContext = createContext<{ start: () => void; running: boolean }>({ start: () => {}, running: false });
export const useTour = () => useContext(TourContext);

// the tour lives above every page, so it survives sign-outs, sign-ins and page loads
export function TourProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<TourState | null>(null);
  useEffect(() => setState(load()), []);
  const update = useCallback((next: TourState | null) => {
    store(next);
    setState(next);
  }, []);
  const start = useCallback(() => update({ step: 0, startedAt: new Date().toISOString(), open: true, vars: {} }), [update]);
  const value = useMemo(() => ({ start, running: !!state }), [start, state]);
  return (
    <TourContext.Provider value={value}>
      {children}
      {state && <TourPanel state={state} update={update} />}
    </TourContext.Provider>
  );
}

// a button to start the tour, for the login page and the sidebar
export function TourButton({ className }: { className?: string }) {
  const { start, running } = useTour();
  if (running) return null;
  return (
    <Button type="button" variant="outline" className={className} onClick={start}>
      <Compass aria-hidden /> Take the guided tour
    </Button>
  );
}

function TourPanel({ state, update }: { state: TourState; update: (s: TourState | null) => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const index = Math.min(state.step, STEPS.length - 1);
  const step = STEPS[index];
  const role = me.data?.role ?? null;
  const roleOk = !step.role || role === step.role;
  const path = step.path?.(state.vars);
  const here = !path || pathname === path;
  const missing = step.needs && state.vars[step.needs] === undefined;

  const check = useQuery({
    queryKey: ["tour", step.id, state.vars],
    queryFn: () => step.check!(state),
    enabled: !!step.check && roleOk && !missing && state.open,
    refetchInterval: 3000,
    retry: false,
  });

  // a check that found the order, the truck or the loom remembers it for later steps
  const found = check.data?.vars;
  useEffect(() => {
    if (!found) return;
    const vars = { ...state.vars, ...found };
    if (JSON.stringify(vars) !== JSON.stringify(state.vars)) update({ ...state, vars });
  }, [found, state, update]);

  if (OUTSIDE.some((p) => pathname.startsWith(p))) return null;

  const done = !step.check || !!check.data?.done;
  const last = index === STEPS.length - 1;
  const next = STEPS[index + 1];

  // demo accounts only: the new login replaces the session cookie (no sign-out gap for a
  // background call to trip over), then the next person's page opens fresh
  async function signInAs(r: Role, to: string) {
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", { method: "POST", json: { email: demoEmail(r), password: DEMO_PASSWORD } });
      qc.clear();
      window.location.assign(to);
    } catch (e) {
      setError(`Could not sign in as ${ROLE_LABEL[r]}: ${(e as Error).message}`);
      setBusy(false);
    }
  }

  function go(to: Step, toIndex: number) {
    const s = { ...state, step: toIndex, open: true };
    update(s);
    const target = to.path?.(s.vars);
    if (to.role && to.role !== role) signInAs(to.role, target ?? "/");
    else if (target && target !== pathname) router.push(target);
  }

  if (!state.open) {
    return (
      <button
        type="button"
        onClick={() => update({ ...state, open: true })}
        className="pressable fixed right-4 bottom-4 z-50 flex max-w-[calc(100vw-2rem)] items-center gap-2 border border-foreground bg-card px-4 py-2.5 text-sm font-semibold shadow-lg"
      >
        <Compass className="size-4 shrink-0 text-ember" aria-hidden />
        <span className="truncate">Tour {index + 1}/{STEPS.length} · {step.title}</span>
      </button>
    );
  }

  return (
    <>
      {roleOk && here && step.target?.(state.vars) && <Spotlight selector={step.target(state.vars)} />}
      <aside
        aria-label="Guided tour"
        className="fixed inset-x-4 bottom-4 z-50 flex max-h-[70dvh] flex-col border border-foreground bg-card text-card-foreground shadow-2xl sm:left-auto sm:w-[25rem]"
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <Compass className="size-4 shrink-0 text-ember" aria-hidden />
          <p className="label min-w-0 flex-1 truncate">{step.scene}</p>
          <span className="num text-xs text-muted-foreground">{index + 1}/{STEPS.length}</span>
          <Button variant="ghost" size="icon-xs" aria-label="Fold the tour away" onClick={() => update({ ...state, open: false })}>
            <ChevronDown aria-hidden />
          </Button>
          <Button variant="ghost" size="icon-xs" aria-label="End the tour" onClick={() => window.confirm("End the guided tour?") && update(null)}>
            <X aria-hidden />
          </Button>
        </div>
        <div className="h-1 bg-border" aria-hidden>
          <div className="h-full bg-ember transition-[width] duration-500" style={{ width: `${((index + (done ? 1 : 0)) / STEPS.length) * 100}%` }} />
        </div>

        <div className="grid gap-3 overflow-y-auto px-4 py-4">
          <h2 className="font-display text-xl leading-tight">{step.title}</h2>
          {step.body(state.vars).map((line) => (
            <p key={line} className="text-sm leading-relaxed text-muted-foreground">{line}</p>
          ))}
          {step.check && <Status step={step} missing={!!missing} roleOk={roleOk} loading={check.isPending} done={done} detail={check.data?.detail ?? check.error?.message} />}
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
          {index > 0 && (
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => go(STEPS[index - 1], index - 1)}>
              <ArrowLeft aria-hidden /> Back
            </Button>
          )}
          <span className="flex-1" />
          {step.role && !roleOk ? (
            <Button size="sm" disabled={busy} onClick={() => signInAs(step.role!, path ?? "/")}>
              {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : <LogIn aria-hidden />} Sign in as {ROLE_LABEL[step.role]}
            </Button>
          ) : !here && path ? (
            <Button size="sm" onClick={() => router.push(path)}>
              Take me there <ArrowRight aria-hidden />
            </Button>
          ) : null}
          {step.check && !done && roleOk && here && (
            <Button variant="ghost" size="sm" onClick={() => go(next ?? step, index + 1)} disabled={busy || last}>
              Skip
            </Button>
          )}
          {(done || !step.check) && (roleOk || !step.role) && (
            <Button size="sm" disabled={busy} onClick={() => (last ? update(null) : go(next, index + 1))}>
              {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : null}
              {last ? "Finish" : next.role && next.role !== role ? `Next: ${ROLE_LABEL[next.role]}` : "Next"}
              {!last && <ArrowRight aria-hidden />}
            </Button>
          )}
        </div>
      </aside>
    </>
  );
}

function Status({ step, missing, roleOk, loading, done, detail }: { step: Step; missing: boolean; roleOk: boolean; loading: boolean; done: boolean; detail?: string }) {
  let text = detail;
  if (missing) text = "An earlier step was skipped, so there is nothing to check here. Go back, or skip on.";
  else if (!roleOk) text = `I check this once you are signed in as ${ROLE_LABEL[step.role!]}.`;
  else if (loading) text = "Checking…";
  return (
    <p role="status" className={cn("flex items-start gap-2 border px-3 py-2 text-sm", done ? "border-success bg-success-soft text-success" : "border-border bg-background")}>
      {done ? <Check className="mt-0.5 size-4 shrink-0" aria-hidden /> : <LoaderCircle className={cn("mt-0.5 size-4 shrink-0 text-ember", !missing && roleOk && "motion-safe:animate-spin")} aria-hidden />}
      <span className="min-w-0">{text}</span>
    </p>
  );
}

// a ring around the thing to press; follows it while the page scrolls or reflows
function Spotlight({ selector }: { selector: string }) {
  const motion = useMotion();
  const [box, setBox] = useState<DOMRect | null>(null);
  useEffect(() => {
    let scrolled = false;
    const measure = () => {
      const el = document.querySelector(selector);
      if (!el) return setBox(null);
      if (!scrolled) {
        el.scrollIntoView({ block: "center", behavior: motion ? "smooth" : "auto" });
        scrolled = true;
      }
      const r = el.getBoundingClientRect();
      setBox((old) => (old && old.top === r.top && old.left === r.left && old.width === r.width && old.height === r.height ? old : r));
    };
    measure();
    const id = window.setInterval(measure, 400);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [selector, motion]);
  if (!box) return null;
  const pad = 6;
  return (
    <div
      aria-hidden
      className={cn("pointer-events-none fixed z-40 border-2 border-ember", motion && "animate-pulse")}
      style={{ top: box.top - pad, left: box.left - pad, width: box.width + pad * 2, height: box.height + pad * 2 }}
    />
  );
}
