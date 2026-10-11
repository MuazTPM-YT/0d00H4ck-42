"use client";

import { Select } from "@/components/ui/select";

import { FastForward } from "lucide-react";
import { type SubmitEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { humanize, metres } from "@/lib/format";
import { qtyLeft } from "@/lib/floor";
import { cn } from "@/lib/utils";
import { validQuantity } from "@/lib/validation";

import { type BoardTile, DOWNTIME, type FastJob, MACHINE_STATUSES, type MachineStatus, useFastFinish, useFloorAction, useRollsToProcess } from "./api";

const QTY_PATTERN = "\\d{1,9}(\\.\\d{1,3})?";
const QTY_TITLE = "A number above 0, up to 3 decimals, e.g. 12.5";

export const selectClass =
  "h-12 w-full rounded-md border border-input bg-transparent px-3 text-base shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive";

// browser checks first (inline message under the field), then the server has the last word
function checked(e: SubmitEvent<HTMLFormElement>, setLocal: (errs: Record<string, string>) => void) {
  e.preventDefault();
  const form = e.currentTarget;
  const bad = Array.from(form.elements).find((el) => el instanceof HTMLInputElement && !el.checkValidity()) as HTMLInputElement | undefined;
  if (bad) {
    setLocal({ [bad.name]: bad.validity.patternMismatch || bad.validity.rangeUnderflow ? bad.title : bad.validationMessage });
    return false;
  }
  setLocal({});
  return true;
}

function FormError({ message }: { message?: string }) {
  return message ? (
    <p role="alert" className="text-sm text-danger">
      {message}
    </p>
  ) : null;
}

export function StatusForm({ tile }: { tile: BoardTile }) {
  const [status, setStatus] = useState<MachineStatus | null>(null);
  const [reason, setReason] = useState("");
  const [local, setLocal] = useState<Record<string, string>>({});
  const save = useFloorAction<object>(() => "/production/machine-events");
  const errors = { ...save.errors, ...local };
  const needsReason = status !== null && DOWNTIME.includes(status);

  return (
    <form
      noValidate
      className="grid gap-3"
      onSubmit={(e) => {
        if (!checked(e, setLocal) || !status) return;
        save.mutate({ machine_id: tile.machine_id, status, reason: needsReason ? reason.trim() : null, source: "manual" });
      }}
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" role="radiogroup" aria-label="New status">
        {MACHINE_STATUSES.filter((s) => s !== tile.status).map((s) => (
          <Button key={s} type="button" role="radio" aria-checked={status === s} variant={status === s ? "default" : "outline"} className="h-12" onClick={() => setStatus(s)}>
            {humanize(s)}
          </Button>
        ))}
      </div>
      {needsReason && (
        <FormField name="reason" label="Reason" error={errors.reason} required hint="What happened, e.g. warp beam snapped">
          <Input id="reason" name="reason" required maxLength={2000} pattern=".*\S.*" title="Give a reason" value={reason} onChange={(e) => setReason(e.target.value)} className="h-12" aria-invalid={!!errors.reason} />
        </FormField>
      )}
      <FormError message={errors.form ?? errors.status ?? errors.machine_id} />
      <Button type="submit" className="h-12" disabled={!status || save.isPending}>
        {save.isPending ? "Saving…" : status ? `Mark ${humanize(status).toLowerCase()}` : "Pick a status"}
      </Button>
    </form>
  );
}

export function OutputForm({ tile }: { tile: BoardTile }) {
  const [value, setValue] = useState("");
  const [local, setLocal] = useState<Record<string, string>>({});
  const save = useFloorAction<object>(() => "/production/output");
  const errors = { ...save.errors, ...local };
  const job = tile.job!;
  return (
    <form
      noValidate
      className="grid gap-3"
      onSubmit={(e) => {
        if (!checked(e, setLocal)) return;
        if (!validQuantity(value)) return setLocal({ qty: QTY_TITLE });
        save.mutate({ machine_id: tile.machine_id, work_order_id: job.work_order_id, qty: value, source: "manual" }, { onSuccess: () => setValue("") });
      }}
    >
      <FormField name="qty" label={`Output (${job.unit === "kg" ? "kg" : "metres"})`} error={errors.qty} required>
        <Input id="qty" name="qty" inputMode="decimal" required pattern={QTY_PATTERN} title={QTY_TITLE} value={value} onChange={(e) => setValue(e.target.value)} className="h-12 text-lg" aria-invalid={!!errors.qty} />
      </FormField>
      <FormError message={errors.form ?? errors.machine_id ?? errors.work_order_id} />
      <Button type="submit" className="h-12" disabled={save.isPending || !Number(value)}>
        {save.isPending ? "Saving…" : "Log output"}
      </Button>
    </form>
  );
}

export function RollForm({ tile }: { tile: BoardTile }) {
  const [value, setValue] = useState("");
  const [local, setLocal] = useState<Record<string, string>>({});
  const save = useFloorAction<object>(() => "/production/rolls");
  const errors = { ...save.errors, ...local };
  return (
    <form
      noValidate
      className="grid gap-3"
      onSubmit={(e) => {
        if (!checked(e, setLocal)) return;
        if (!validQuantity(value, 1000)) return setLocal({ length_m: "Enter 0.001 to 1000 metres, up to 3 decimals" });
        save.mutate({ work_order_id: tile.job!.work_order_id, length_m: value, source: "manual" }, { onSuccess: () => setValue("") });
      }}
    >
      <FormField name="length_m" label="Roll length (metres)" error={errors.length_m} required hint="Up to 1000 m">
        <Input id="length_m" name="length_m" inputMode="decimal" required pattern={QTY_PATTERN} title={QTY_TITLE} value={value} onChange={(e) => setValue(e.target.value)} className="h-12 text-lg" aria-invalid={!!errors.length_m} />
      </FormField>
      <FormError message={errors.form ?? errors.work_order_id} />
      <Button type="submit" className="h-12" disabled={save.isPending || !Number(value)}>
        {save.isPending ? "Saving…" : "Cut roll"}
      </Button>
    </form>
  );
}

// dyeing takes a woven roll of the same order; a rework job takes its one roll
export function ProcessRollForm({ tile, reworkRollId }: { tile: BoardTile; reworkRollId: number | null }) {
  const job = tile.job!;
  const rolls = useRollsToProcess(reworkRollId ? null : job.order_id);
  const [rollId, setRollId] = useState("");
  const save = useFloorAction<{ roll: string; work_order_id: number; source: string }>((b) => `/production/rolls/${b.roll}/process`);
  const chosen = reworkRollId ? String(reworkRollId) : rollId;
  const options = rolls.data?.items ?? [];

  return (
    <form
      className="grid gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!chosen) return;
        save.mutate({ roll: chosen, work_order_id: job.work_order_id, source: "manual" }, { onSuccess: () => setRollId("") });
      }}
    >
      {!reworkRollId && (
        <FormField name="roll" label="Roll" required error={rolls.isError ? rolls.error.message : undefined} hint={rolls.isSuccess && options.length === 0 ? "No woven rolls of this order are waiting." : undefined}>
          <Select id="roll" name="roll" required value={rollId} onChange={(e) => setRollId(e.target.value)} className={selectClass} disabled={rolls.isPending}>
            <option value="">{rolls.isPending ? "Loading rolls…" : "Pick a roll"}</option>
            {options.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code} · {metres(r.length_m)}
              </option>
            ))}
          </Select>
        </FormField>
      )}
      <FormError message={save.errors.form ?? save.errors.work_order_id} />
      <Button type="submit" className="h-12" disabled={save.isPending || !chosen}>
        {save.isPending ? "Saving…" : reworkRollId ? "Process roll" : "Roll processed"}
      </Button>
      {!reworkRollId && <DyeAllButton tile={tile} waiting={rolls.data?.total ?? 0} />}
    </form>
  );
}

// a jigger batch: every woven roll of the order that waits goes through in one go
function DyeAllButton({ tile, waiting }: { tile: BoardTile; waiting: number }) {
  const job = tile.job!;
  const save = useFloorAction<{ source: string }>(() => `/production/work-orders/${job.work_order_id}/process-waiting`);
  return (
    <div className="grid gap-2 border-t border-dashed border-border pt-3">
      <Button type="button" variant="outline" className="h-12" disabled={save.isPending || waiting === 0 || job.status !== "running"} onClick={() => save.mutate({ source: "manual" })}>
        {save.isPending ? "Dyeing…" : (
          <>
            Dye all waiting rolls (<span className="num">{waiting}</span>)
          </>
        )}
      </Button>
      <FormError message={save.errors.form ?? save.errors.work_order_id} />
    </div>
  );
}

// the demo can't wait for a loom at live speed: one press makes the rest of the plan
export function FastFinishButton({ job, className }: { job: FastJob; className?: string }) {
  const fast = useFastFinish();
  const hint = job.stage === "dyeing" ? "Dye every waiting roll now" : `Make the last ${metres(qtyLeft(job.planned, job.produced))} now; the loom cuts the tail roll and finishes`;
  return (
    <div className={cn("grid gap-1", className)}>
      <Button variant="outline" onClick={() => fast.mutate(job)} disabled={fast.isPending} title={hint} data-tour="fast-finish">
        <FastForward /> {fast.isPending ? "Finishing…" : "Fast finish"}
      </Button>
      {fast.isError && <p role="alert" className="text-sm text-danger">{fast.error.message}</p>}
    </div>
  );
}
