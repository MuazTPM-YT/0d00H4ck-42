"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, Link2, Mail, MessageCircle, RefreshCw, Send } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { ReasonAction } from "@/components/layout/ReasonAction";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { date, dateTime, inr, metres } from "@/lib/format";
import { copyText, whatsappNumber } from "@/lib/share";
import { useSSE } from "@/lib/useSSE";
import { tripStatus } from "@/features/dispatch/types";

import { StageCard, Timeline, type Track } from "./StageCard";

type OrderView = Track & {
  order_id: number;
  order_status: string;
  buyer_name: string;
  buyer_contact: string | null;
  buyer_phone: string | null;
  buyer_email: string | null;
  tracking_token: string;
  mail_on: boolean;
  link_email: { status: "sent" | "failed" | "skipped"; at: string; to: string | null; error: string | null } | null;
  rolls: { id: number; code: string; length_m: string; status: string; shade_band: string | null; dispatch_code: string | null }[];
  dispatches: { id: number; code: string; status: string; vehicle_no: string | null; confirmed_at: string | null; delivered_at: string | null; roll_count: number; metres: string }[];
  invoices: { id: number; code: string; total_paise: number; paid_paise: number; status: string; due_date: string }[];
};

// one order: where it is, when it ships, and every roll, truck and invoice behind that answer
export function OrderDetail({ id, costPanel, yarnPanel }: { id: string; costPanel?: ReactNode; yarnPanel?: ReactNode }) {
  useSSE(["orders", "dispatch", "quality", "machines"]);
  const role = useMe().data?.role;
  const view = useQuery({ queryKey: ["orders", "view", id], queryFn: () => api<OrderView>(`/track/orders/${id}`) });
  const qc = useQueryClient();

  if (view.isPending) return <Skeleton className="h-96 w-full" />;
  if (view.isError) {
    return (
      <EmptyState icon={AlertTriangle} title="Could not load this order" action={<Button variant="outline" onClick={() => view.refetch()}>Try again</Button>}>
        {view.error.message}
      </EmptyState>
    );
  }
  const o = view.data;

  return (
    <>
      <PageHeader title={`${o.order_code} · ${o.buyer_name}`} actions={<StatusBadge status={o.order_status} className="text-sm" />} />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="grid content-start gap-6">
          <StageCard t={o} />
          {yarnPanel && <section className="border border-border bg-card p-4">{yarnPanel}</section>}
          {costPanel}
          <Section title={`Rolls (${o.rolls.length})`} empty="No rolls woven yet.">
            {o.rolls.length > 0 && (
              <Table containerClassName="scroll-panel max-h-[28rem]">
                <TableHeader className="sticky top-0 z-10 bg-card">
                  <TableRow>
                    <TableHead>Roll</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Shade</TableHead>
                    <TableHead>Dispatch</TableHead>
                    <TableHead className="text-right">Metres</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {o.rolls.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>
                        <Link href={`/qc/rolls/${r.id}`} className="num font-semibold hover:text-ember">
                          {r.code}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={r.status} />
                      </TableCell>
                      <TableCell>{r.shade_band ?? "—"}</TableCell>
                      <TableCell>{r.dispatch_code ?? "—"}</TableCell>
                      <TableCell className="tabular text-right">{metres(r.length_m)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>
          <Section title="Dispatches" empty="Nothing shipped yet.">
            {o.dispatches.length > 0 && (
              <ul className="divide-y text-sm">
                {o.dispatches.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-3 px-4 py-2">
                    <span className="font-medium">{d.code}</span>
                    <StatusBadge status={tripStatus(d)} />
                    <span className="text-muted-foreground">{d.vehicle_no ?? "no vehicle"} · {dateTime(d.confirmed_at)}</span>
                    <span className="ml-auto tabular">{d.roll_count} rolls · {metres(d.metres)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section title="Invoices" empty="No invoices yet.">
            {o.invoices.length > 0 && (
              <ul className="divide-y text-sm">
                {o.invoices.map((i) => (
                  <li key={i.id} className="flex flex-wrap items-center gap-3 px-4 py-2">
                    <span className="font-medium">{i.code}</span>
                    <StatusBadge status={i.status} />
                    <span className="text-muted-foreground">due {date(i.due_date)}</span>
                    <span className="ml-auto tabular">{inr(i.paid_paise)} of {inr(i.total_paise)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
        <div className="grid content-start gap-6">
          {(role === "accounts" || role === "owner") && (o.order_status === "draft" || o.order_status === "confirmed") && (
            <section className="grid gap-2 border border-border bg-card p-4">
              <h2 className="text-base">Cancel order</h2>
              <p className="text-sm text-muted-foreground">Frees reserved yarn and takes queued jobs off the machines. A job still running is finished on the floor first.</p>
              <ReasonAction label="Cancel order" question="Why is this order cancelled?" url={`/orders/${o.order_id}/cancel`} onDone={() => qc.invalidateQueries({ queryKey: ["orders"] })} />
            </section>
          )}
          <BuyerLink o={o} canRotate={role === "accounts" || role === "owner"} />
          <Timeline events={o.timeline} />
        </div>
      </div>
    </>
  );
}

function Section({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  return (
    <section className="border border-border bg-card">
      <h2 className="border-b border-border px-4 py-3 text-base">{title}</h2>
      <div className="overflow-x-auto">{children || <p className="px-4 py-6 text-sm text-muted-foreground">{empty}</p>}</div>
    </section>
  );
}

// the buyer's read-only link; replacing it kills the old one at once
function BuyerLink({ o, canRotate }: { o: OrderView; canRotate: boolean }) {
  const qc = useQueryClient();
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const url = typeof window === "undefined" ? "" : `${window.location.origin}/track/${o.tracking_token}`;
  const message = `Hello ${o.buyer_contact ?? o.buyer_name}, you can track your order ${o.order_code} (${o.fabric}, ${o.colour}) any time here: ${url}`;
  const whatsapp = `https://wa.me/${whatsappNumber(o.buyer_phone)}?text=${encodeURIComponent(message)}`;
  const email = `mailto:${o.buyer_email ?? ""}?subject=${encodeURIComponent(`Order ${o.order_code}: tracking link`)}&body=${encodeURIComponent(message)}`;
  const rotate = useMutation({
    mutationFn: () => api(`/track/orders/${o.order_id}/rotate-token`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders", "view"] }),
  });
  const send = useMutation({
    mutationFn: () => api(`/track/orders/${o.order_id}/email-link`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders", "view"] }),
  });
  async function onCopy() {
    setCopy((await copyText(url)) ? "copied" : "failed");
    setTimeout(() => setCopy("idle"), 2000);
  }
  return (
    <section className="grid gap-2 border border-border bg-card p-4 text-sm">
      <h2 className="flex items-center gap-2 font-medium"><Link2 className="size-4" aria-hidden /> Buyer tracking link</h2>
      <p className="break-all text-muted-foreground">{url}</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={onCopy}>
          {copy === "copied" ? <Check /> : <Copy />} {copy === "copied" ? "Copied" : "Copy link"}
        </Button>
        <Button variant="outline" size="sm" asChild>
          <a href={whatsapp} target="_blank" rel="noopener noreferrer" title={o.buyer_phone ? `Send to ${o.buyer_phone}` : "Pick a contact in WhatsApp"}>
            <MessageCircle /> WhatsApp
          </a>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <a href={email} title={o.buyer_email ? `Send to ${o.buyer_email}` : "No email on file; add one in the mail app"}>
            <Mail /> Email
          </a>
        </Button>
        {canRotate && o.mail_on && (
          <Button variant="outline" size="sm" disabled={send.isPending} onClick={() => send.mutate()}>
            <Send /> {send.isPending ? "Sending…" : o.link_email ? "Resend email" : "Send email"}
          </Button>
        )}
        {canRotate && (
          <Button variant="outline" size="sm" disabled={rotate.isPending} onClick={() => window.confirm("The old link stops working. Continue?") && rotate.mutate()}>
            <RefreshCw /> New link
          </Button>
        )}
      </div>
      {copy === "failed" && <p role="alert" className="text-danger">Could not copy. Select the link above and copy it by hand.</p>}
      {rotate.isError && <p role="alert" className="text-danger">{rotate.error.message}</p>}
      {send.isError && <p role="alert" className="text-danger">{send.error.message}</p>}
      <EmailStatus o={o} />
    </section>
  );
}

// what happened to the automatic "order confirmed" email, so the clerk knows whether to follow up
function EmailStatus({ o }: { o: OrderView }) {
  const e = o.link_email;
  if (!o.mail_on) return <p className="text-muted-foreground">Automatic email is off: no mail server is set in .env.</p>;
  if (!e) return <p className="text-muted-foreground">The link is emailed to the buyer when the order is confirmed.</p>;
  if (e.status === "sent") return <p className="text-success">Emailed to {e.to} on {dateTime(e.at)}.</p>;
  if (e.status === "skipped") return <p className="text-warning">Not emailed: the buyer has no email address. Add one in Masters → Buyers, then send.</p>;
  return <p role="alert" className="text-danger">Email to {e.to} failed on {dateTime(e.at)}: {e.error}</p>;
}
