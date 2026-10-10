"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { Row } from "./config";
import { useMasterForm } from "./useMasterForm";

type Stage = "spinning" | "weaving" | "dyeing";
type Recipe = { fibre: string; count: string; share_pct: string };
export type FabricRow = Row & {
  code: string; name: string; width_cm: string; gsm: string; process_loss_pct: string; active: boolean;
  stages: { seq: number; stage: Stage }[];
  recipe: Recipe[];
};

const STAGES: Stage[] = ["spinning", "weaving", "dyeing"];
const selectClass = "h-9 rounded-md border border-input bg-transparent px-3 text-sm shadow-xs capitalize";

// route = ordered stages; recipe = yarn shares adding up to 100%
export function FabricTypeForm({ row, onDone }: { row: FabricRow | null; onDone: () => void }) {
  const [head, setHead] = useState({
    code: row?.code ?? "", name: row?.name ?? "", width_cm: row ? String(Number(row.width_cm)) : "",
    gsm: row ? String(Number(row.gsm)) : "", process_loss_pct: row ? String(Number(row.process_loss_pct)) : "",
    active: row?.active ?? true,
  });
  const [stages, setStages] = useState<Stage[]>(row?.stages.map((s) => s.stage) ?? ["weaving"]);
  const [recipe, setRecipe] = useState<Recipe[]>(
    row?.recipe.map((r) => ({ ...r, share_pct: String(Number(r.share_pct)) })) ?? [{ fibre: "Cotton", count: "", share_pct: "100" }],
  );
  const { errors, save, formProps, submit } = useMasterForm("fabric-types", row?.id ?? null, onDone);

  const shareTotal = recipe.reduce((sum, r) => sum + (Number(r.share_pct) || 0), 0);
  const err = (prefix: string) => Object.entries(errors).find(([k]) => k === prefix || k.startsWith(`${prefix}.`))?.[1];

  const body = () => ({
    ...head,
    code: head.code.trim(), name: head.name.trim(),
    stages: stages.map((stage, i) => ({ seq: i + 1, stage })),
    recipe: recipe.map((r) => ({ fibre: r.fibre.trim(), count: r.count.trim(), share_pct: r.share_pct })),
  });

  const headField = (name: keyof typeof head, label: string, extra: Record<string, unknown>, hint?: string) => (
    <FormField name={name} label={label} error={errors[name]} hint={hint} required>
      <Input
        id={name} name={name} required value={head[name] as string}
        onChange={(e) => setHead((h) => ({ ...h, [name]: e.target.value }))}
        aria-invalid={!!errors[name]} aria-describedby={errors[name] ? `${name}-error` : undefined}
        {...extra}
      />
    </FormField>
  );

  return (
    <form {...formProps} onSubmit={(e) => submit(e, body)} className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {headField("code", "Code", { maxLength: 20, pattern: "[A-Za-z0-9][A-Za-z0-9\\-]{0,19}" })}
        {headField("name", "Name", { maxLength: 120 })}
        {headField("width_cm", "Width (cm)", { type: "number", min: 0.01, step: "0.01" })}
        {headField("gsm", "GSM", { type: "number", min: 0.01, step: "0.01" }, "Grams per square metre")}
        {headField("process_loss_pct", "Process loss (%)", { type: "number", min: 0, max: 99.99, step: "0.01" }, "Yarn lost between yarn and finished fabric")}
      </div>

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Route</legend>
        <p className="text-xs text-muted-foreground">Stages in order. Every fabric is woven; add dyeing for piece-dyed fabric.</p>
        <ol className="grid gap-2">
          {stages.map((stage, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="w-5 text-sm text-muted-foreground tabular">{i + 1}.</span>
              <select aria-label={`Stage ${i + 1}`} value={stage} onChange={(e) => setStages((s) => s.map((x, j) => (j === i ? (e.target.value as Stage) : x)))} className={cn(selectClass, "flex-1")}>
                {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove stage ${i + 1}`} disabled={stages.length === 1} onClick={() => setStages((s) => s.filter((_, j) => j !== i))}>
                <X />
              </Button>
            </li>
          ))}
        </ol>
        {stages.length < STAGES.length && (
          <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => setStages((s) => [...s, STAGES.find((x) => !s.includes(x))!])}>
            <Plus /> Add stage
          </Button>
        )}
        {err("stages") && <p role="alert" className="text-sm text-danger">{err("stages")}</p>}
      </fieldset>

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Yarn recipe</legend>
        {recipe.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_5rem_auto] items-center gap-2">
            <Input aria-label={`Fibre ${i + 1}`} placeholder="Fibre" required maxLength={40} value={r.fibre} onChange={(e) => setRecipe((rs) => rs.map((x, j) => (j === i ? { ...x, fibre: e.target.value } : x)))} />
            <Input aria-label={`Count ${i + 1}`} placeholder="Ne 30/1" required maxLength={20} value={r.count} onChange={(e) => setRecipe((rs) => rs.map((x, j) => (j === i ? { ...x, count: e.target.value } : x)))} />
            <Input aria-label={`Share ${i + 1} (%)`} type="number" min={0.01} max={100} step="0.01" required value={r.share_pct} onChange={(e) => setRecipe((rs) => rs.map((x, j) => (j === i ? { ...x, share_pct: e.target.value } : x)))} />
            <Button type="button" variant="ghost" size="icon" aria-label={`Remove yarn ${i + 1}`} disabled={recipe.length === 1} onClick={() => setRecipe((rs) => rs.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </div>
        ))}
        <div className="flex items-center justify-between gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => setRecipe((rs) => [...rs, { fibre: "Cotton", count: "", share_pct: "" }])}>
            <Plus /> Add yarn
          </Button>
          <span className={cn("text-sm tabular", shareTotal === 100 ? "text-success" : "text-warning")}>Total {shareTotal}% of 100%</span>
        </div>
        {err("recipe") && <p role="alert" className="text-sm text-danger">{err("recipe")}</p>}
      </fieldset>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={head.active} onChange={(e) => setHead((h) => ({ ...h, active: e.target.checked }))} className="size-4 accent-primary" />
        Active
      </label>

      {errors.form && <p role="alert" className="text-sm text-danger">{errors.form}</p>}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>Cancel</Button>
        <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : row ? "Save changes" : "Add fabric type"}</Button>
      </DialogFooter>
    </form>
  );
}
