import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { FormField } from "@/components/layout/FormField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

// a button that asks why before it posts { reason } to one endpoint (cancel order, cancel delivery)
export function ReasonAction({ label, question, url, onDone }: { label: string; question: string; url: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();
  const save = useMutation({
    mutationFn: () => api(url, { method: "POST", json: { reason: reason.trim() } }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      onDone();
    },
    onError: (e) => setError(e.message),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!reason.trim()) return setError("A reason is required");
    save.mutate();
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        {label}
      </Button>
    );
  }
  return (
    <form onSubmit={submit} noValidate className="grid w-full max-w-md gap-3 border p-3">
      <FormField name="reason" label={question} error={error} required>
        <Input id="reason" name="reason" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} aria-invalid={!!error} aria-describedby={error ? "reason-error" : undefined} autoFocus />
      </FormField>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="destructive" disabled={save.isPending}>
          {save.isPending ? "Saving…" : label}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Keep it
        </Button>
      </div>
    </form>
  );
}
