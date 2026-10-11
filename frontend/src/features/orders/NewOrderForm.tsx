"use client";

import { Select } from "@/components/ui/select";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { kg, rupeesToPaise } from "@/lib/format";
import { useSSE } from "@/lib/useSSE";
import { millDate, validDate, validQuantity } from "@/lib/validation";

import { selectClass, useMaster, type NamedOption, type YarnItemOption } from "@/features/inventory/ui";

import { OrderYarnPanel } from "./OrderYarnPanel";
import type { Order, YarnLine } from "./types";

const METRES_RE = /^\d+(\.\d{1,3})?$/;

type FabricOption = NamedOption & { stages: { seq: number; stage: string }[]; recipe: { fibre: string; count: string }[] };

// colours that exist as a yarn item for every (fibre, count) of the recipe; others would deadlock
function recipeColours(fabric: FabricOption, items: YarnItemOption[]): string[] {
  const low = (x: string) => x.trim().toLowerCase();
  const perLine = fabric.recipe.map((r) => {
    const here = new Map<string, string>();
    for (const i of items) if (low(i.fibre) === low(r.fibre) && low(i.count) === low(r.count)) here.set(low(i.colour), i.colour);
    return here;
  });
  if (!perLine.length) return [];
  const [first, ...rest] = perLine;
  return [...first.entries()]
    .filter(([k]) => rest.every((m) => m.has(k)))
    .map(([, colour]) => colour)
    .sort((a, b) => a.localeCompare(b));
}

// IST tomorrow; UTC gave today before 5:30 am, which the server rejects
const tomorrow = () => millDate(1);

// wait until typing pauses before asking the server
function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// R4: enter the order, see needed / free / short per yarn while typing, then confirm
export function NewOrderForm() {
  useSSE(["stock", "orders"]);
  const qc = useQueryClient();
  const buyers = useMaster<NamedOption>("buyers");
  const fabrics = useMaster<FabricOption>("fabric-types");
  const yarnItems = useMaster<YarnItemOption>("yarn-items");
  const [v, setV] = useState({ buyer_id: "", fabric_type_id: "", colour: "", qty_m: "", rate: "", deadline: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirmedId, setConfirmedId] = useState<number | null>(null);
  const set = (k: keyof typeof v, value: string) => setV((p) => ({ ...p, [k]: value }));
  const fabric = fabrics.data?.items.find((f) => String(f.id) === v.fabric_type_id);
  const dyed = !!fabric?.stages.some((st) => st.stage === "dyeing");
  // undyed fabric: yarn colour = order colour, so only colours the yarn masters hold
  const colours = useMemo(() => (fabric && !dyed ? recipeColours(fabric, yarnItems.data?.items ?? []) : null), [fabric, dyed, yarnItems.data]);

  const previewInput = useDebounced({ fabric: v.fabric_type_id, colour: v.colour.trim(), qty: v.qty_m });
  const previewReady = !!previewInput.fabric && !!previewInput.colour && previewInput.colour.length <= 40 && validQuantity(previewInput.qty, 1_000_000);
  const preview = useQuery({
    queryKey: ["stock", "requirement-preview", previewInput],
    queryFn: () =>
      api<YarnLine[]>("/orders/requirement-preview", {
        method: "POST",
        json: { fabric_type_id: Number(previewInput.fabric), colour: previewInput.colour, qty_m: previewInput.qty },
      }),
    enabled: previewReady,
  });

  const save = useMutation({
    // a failed confirm leaves a saved draft; report it instead of letting a retry create a twin
    mutationFn: async ({ body, confirm }: { body: object; confirm: boolean }) => {
      const order = await api<Order>("/orders", { method: "POST", json: body });
      if (!confirm) return { order, confirm, confirmError: null };
      try {
        await api(`/orders/${order.id}/confirm`, { method: "POST" });
        return { order, confirm, confirmError: null };
      } catch (e) {
        return { order, confirm: false, confirmError: (e as Error).message };
      }
    },
    onSuccess: ({ order }) => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["stock"] });
      setConfirmedId(order.id);
    },
    onError: (e) => setErrors({ [e instanceof ApiError && e.field ? fieldFor(e.field) : "form"]: e.message }),
  });

  function submit(confirm: boolean) {
    const errs: Record<string, string> = {};
    if (!v.buyer_id) errs.buyer_id = "Pick the buyer";
    if (!v.fabric_type_id) errs.fabric_type_id = "Pick the fabric";
    if (!v.colour.trim() || v.colour.trim().length > 40) errs.colour = "Colour is required, up to 40 characters";
    if (!validQuantity(v.qty_m, 1_000_000)) errs.qty_m = "Enter 0.001 to 1,000,000 metres, up to 3 decimals";
    const paise = rupeesToPaise(v.rate);
    if (!paise) errs.rate = "Rupees per metre above 0, e.g. 185 or 185.50";
    if (!v.deadline || v.deadline < tomorrow()) errs.deadline = "Deadline must be after today";
    else if (!validDate(v.deadline, tomorrow(), millDate(730))) errs.deadline = "Pick a valid deadline within two years";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    save.mutate({
      confirm,
      body: { buyer_id: Number(v.buyer_id), fabric_type_id: Number(v.fabric_type_id), colour: v.colour.trim(), qty_m: v.qty_m, rate_paise_per_m: paise, deadline: v.deadline },
    });
  }

  const a11y = (name: string) => ({ "aria-invalid": !!errors[name], "aria-describedby": errors[name] ? `${name}-error` : undefined });

  if (confirmedId !== null && save.data) {
    return (
      <>
        <PageHeader title={`Order ${save.data.order.code}`} description={save.data.confirm ? "Confirmed. Work orders are planned and free yarn is reserved." : "Saved as draft. Confirm it from the orders list."} />
        <div className="grid gap-4">
          {save.data.confirmError ? (
            <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">Saved as draft but not confirmed: {save.data.confirmError}</p>
          ) : (
            <p role="status" className="flex items-center gap-2 text-success"><CheckCircle2 aria-hidden /> {save.data.confirm ? "Confirmed" : "Draft saved"}</p>
          )}
          <OrderYarnPanel orderId={confirmedId} />
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline"><Link href="/orders">Back to orders</Link></Button>
            <Button onClick={() => { setConfirmedId(null); save.reset(); setV({ buyer_id: "", fabric_type_id: "", colour: "", qty_m: "", rate: "", deadline: "" }); }}>Enter another order</Button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title="New order" description="Yarn needed = metres × width × GSM ÷ 1000 ÷ (1 − loss%), split by the fabric recipe. Dyed fabrics use Raw White yarn." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <form noValidate data-tour="order-form" onSubmit={(e: FormEvent) => { e.preventDefault(); submit(true); }} className="grid content-start gap-4 rounded-lg border bg-card p-4">
          <FormField name="buyer_id" label="Buyer" error={errors.buyer_id} required>
            <Select id="buyer_id" value={v.buyer_id} onChange={(e) => set("buyer_id", e.target.value)} className={selectClass} {...a11y("buyer_id")}>
              <option value="">Choose…</option>
              {buyers.data?.items.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </FormField>
          <FormField name="fabric_type_id" label="Fabric" error={errors.fabric_type_id} required>
            <Select id="fabric_type_id" value={v.fabric_type_id} onChange={(e) => setV((p) => ({ ...p, fabric_type_id: e.target.value, colour: "" }))} className={selectClass} {...a11y("fabric_type_id")}>
              <option value="">Choose…</option>
              {fabrics.data?.items.map((f) => <option key={f.id} value={f.id}>{`${f.code} · ${f.name}`}</option>)}
            </Select>
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              name="colour"
              label="Colour"
              error={errors.colour}
              required
              hint={
                colours
                  ? yarnItems.isPending
                    ? "Loading yarn colours…"
                    : colours.length
                      ? "Colours that exist in the yarn masters for this fabric."
                      : "No yarn colour exists for every yarn of this recipe. Add the yarn items in Masters."
                  : dyed
                    ? "Dyed after weaving: any shade. Woven from Raw White yarn."
                    : undefined
              }
            >
              {colours ? (
                <select id="colour" value={v.colour} onChange={(e) => set("colour", e.target.value)} className={selectClass} disabled={!colours.length} {...a11y("colour")}>
                  <option value="">Choose…</option>
                  {colours.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <Input id="colour" value={v.colour} maxLength={40} onChange={(e) => set("colour", e.target.value)} {...a11y("colour")} />
              )}
            </FormField>
            <FormField name="qty_m" label="Metres" error={errors.qty_m} required>
              <Input id="qty_m" inputMode="decimal" value={v.qty_m} onChange={(e) => set("qty_m", e.target.value)} {...a11y("qty_m")} />
            </FormField>
            <FormField name="rate" label="Rate (₹ per metre)" error={errors.rate} required>
              <Input id="rate" inputMode="decimal" value={v.rate} onChange={(e) => set("rate", e.target.value)} {...a11y("rate")} />
            </FormField>
            <FormField name="deadline" label="Deadline" error={errors.deadline} required>
              <Input id="deadline" type="date" min={tomorrow()} max={millDate(730)} value={v.deadline} onChange={(e) => set("deadline", e.target.value)} {...a11y("deadline")} />
            </FormField>
          </div>
          {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" size="lg" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save and confirm"}</Button>
            <Button type="button" size="lg" variant="outline" disabled={save.isPending} onClick={() => submit(false)}>Save as draft</Button>
          </div>
        </form>

        <section className="grid content-start gap-3 rounded-lg border bg-card p-4" aria-live="polite">
          <h2 className="font-semibold">Yarn check</h2>
          {!previewReady ? (
            <p className="text-sm text-muted-foreground">Pick a fabric, colour and metres to see if the yarn is there.</p>
          ) : preview.isError ? (
            <p role="alert" className="text-sm text-danger">{preview.error.message}</p>
          ) : preview.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 font-medium">Yarn</th>
                    <th className="py-1 text-right font-medium">Needed</th>
                    <th className="py-1 text-right font-medium">Free</th>
                    <th className="py-1 text-right font-medium">Short</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.map((l) => (
                    <tr key={`${l.count}-${l.colour}`} className="border-t">
                      <td className="py-2">
                        {l.fibre} {l.count} {l.colour}
                        {l.not_in_masters && <div className="text-xs text-danger">Not in yarn masters</div>}
                      </td>
                      <td className="py-2 text-right">{kg(l.kg_needed)}</td>
                      <td className="py-2 text-right">{kg(l.kg_free)}</td>
                      <td className={Number(l.kg_short) > 0 ? "py-2 text-right font-semibold text-danger" : "py-2 text-right text-success"}>{kg(l.kg_short)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.data.some((l) => l.not_in_masters) && (
                <p role="alert" className="rounded-md bg-danger-soft p-3 text-sm text-danger">
                  {dyed
                    ? "Raw White yarn for this recipe is not in the yarn masters. Add it before yarn can be reserved or bought."
                    : "No yarn item in masters for this colour, so the order cannot be confirmed. Pick a listed colour or add the yarn item first."}
                </p>
              )}
              {preview.data.some((l) => Number(l.kg_short) > 0) ? (
                <p className="rounded-md bg-warning-soft p-3 text-sm text-warning">Not enough yarn to start. Confirming still reserves what is free; the rest goes on the to-buy list.</p>
              ) : (
                <p className="rounded-md bg-success-soft p-3 text-sm text-success">Enough free yarn to start this order.</p>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}

const fieldFor = (f: string) => (f === "rate_paise_per_m" ? "rate" : f);
