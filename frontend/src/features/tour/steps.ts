import { api, type Paged } from "@/lib/api";
import type { Role } from "@/lib/auth";
import { kg, metres } from "@/lib/format";

// what the tour remembers between steps (and across sign-ins): the things it made happen
export type TourVars = {
  orderId?: number;
  orderCode?: string;
  receiptId?: number;
  receiptCode?: string;
  loom?: string;
  rollId?: number;
  truckId?: number;
  truckCode?: string;
};

export type TourState = { step: number; startedAt: string; open: boolean; vars: TourVars };

// done: the fact the step asks for is in the database; detail: one live line for the panel
export type Check = { done: boolean; detail?: string; vars?: TourVars };

export type Step = {
  id: string;
  scene: string;
  role: Role | null; // null: any login (or none)
  title: string;
  body: (v: TourVars) => string[];
  path?: (v: TourVars) => string;
  target?: (v: TourVars) => string; // CSS selector to ring on the page
  check?: (s: TourState) => Promise<Check>;
  needs?: keyof TourVars; // the check reads this; missing means an earlier step was skipped
};

type WorkOrder = { id: number; code: string; stage: string; seq: number; status: string; machine_id: number | null; queue_position: number | null; roll_id: number | null };
type Tile = { code: string; status: string; job: { order_id: number; stage: string; status: string; planned: string; produced: string } | null };
type Roll = { id: number; code: string; status: string };

// the clock on this screen and the server's may differ a little
const since = (s: TourState, at: string | null | undefined) => !!at && Date.parse(at) >= Date.parse(s.startedAt) - 120_000;

async function mains(orderId: number) {
  const r = await api<Paged<WorkOrder>>(`/production/work-orders?order_id=${orderId}&limit=50`);
  return r.items.filter((w) => w.roll_id === null).sort((a, b) => a.seq - b.seq);
}

async function rolls(orderId: number) {
  const r = await api<Paged<Roll>>(`/quality/rolls?order_id=${orderId}&limit=200`);
  const count = (...st: string[]) => r.items.filter((x) => st.includes(x.status)).length;
  return { items: r.items, count };
}

type OpenJob = { id: number; order_id: number; stage: string; status: string; planned_qty: string; produced: string; unit: string; roll_id: number | null };

// "weaving done · dyeing queued 0 of 116 m"
async function progressLine(orderId: number) {
  const [jobs, open] = await Promise.all([mains(orderId), api<OpenJob[]>("/production/work-orders/open")]);
  const byId = new Map(open.map((j) => [j.id, j]));
  return jobs
    .map((w) => {
      const j = byId.get(w.id);
      if (!j) return `${w.stage} ${w.status}`;
      return `${w.stage} ${w.status} ${Number(j.produced).toFixed(0)} of ${Number(j.planned_qty).toFixed(0)} ${j.unit}`;
    })
    .join(" · ");
}

export const STEPS: Step[] = [
  {
    id: "welcome",
    scene: "Welcome",
    role: null,
    title: "One order, from yarn at the gate to money in the bank",
    body: () => [
      "I'll walk you through Everest Textile Mills the way the problem statement tells it: yarn arrives, the floor weaves, QC checks every roll, the buyer asks, a truck leaves, the month closes.",
      "We follow one real order the whole way. Nothing is staged: each step waits until the database shows the thing happened.",
      "I sign you in as each person in turn. Keep to this one window.",
    ],
  },
  {
    id: "owner",
    scene: "Opening · Owner",
    role: "owner",
    title: "The owner's morning",
    path: () => "/owner",
    target: () => "[data-tour=briefing]",
    body: () => [
      "The briefing and the list under it are worked out from live data: machines stopped, rolls waiting, yarn below reorder, invoices overdue.",
      "Delivery risk is a forecast from real output rates, not a status someone typed.",
    ],
  },
  {
    id: "receive",
    scene: "Scene 1 · Yarn at the gate",
    role: "store",
    title: "A truck of yarn arrives",
    path: () => "/store/receive",
    target: () => "[data-tour=receive-lots]",
    body: () => [
      "Tap a sample label below the scan box (or scan a printed one with the camera). The label is checked against what was ordered: a wrong spec goes to quarantine, a weight gap over 2% is flagged.",
      "Press Add lot, then Confirm receipt.",
    ],
    check: async (s) => {
      const r = await api<Paged<{ id: number; code: string; confirmed_at: string | null; total_kg: string }>>("/inventory/receipts?status=confirmed&limit=5");
      const hit = r.items.find((x) => since(s, x.confirmed_at));
      if (!hit) return { done: false, detail: "Waiting for you to confirm a receipt" };
      return { done: true, detail: `${hit.code} confirmed: ${kg(hit.total_kg)}`, vars: { receiptId: hit.id, receiptCode: hit.code } };
    },
  },
  {
    id: "approve",
    needs: "receiptId",
    scene: "Scene 1 · Yarn at the gate",
    role: "store",
    title: "Inspect, then approve into the store",
    path: () => "/store/batches",
    body: (v) => [
      `The lots on ${v.receiptCode ?? "the truck"} sit in inspection: on the books but not usable yet.`,
      "Open each lot and press Approve into store. Approved yarn is reserved for any order that was short, earliest deadline first.",
    ],
    check: async (s) => {
      const r = await api<{ batches: { status: string }[] }>(`/inventory/receipts/${s.vars.receiptId}`);
      const open = r.batches.filter((b) => b.status === "inspection" || b.status === "pending_identification").length;
      return { done: open === 0, detail: open ? `${open} of ${r.batches.length} lots still in inspection` : "All lots decided" };
    },
  },
  {
    id: "order",
    scene: "Scene 1 · Yarn at the gate",
    role: "accounts",
    title: "A buyer places an order",
    path: () => "/orders/new",
    target: () => "[data-tour=order-form]",
    body: () => [
      "Buyer: Gowda Uniforms. Fabric: Piece-dyed Poplin. Colour: Navy. Quantity: 110 m. Rate: 185. Deadline: any day next month.",
      "Watch the yarn panel while you type: needed, free and short kilos, live from the stock ledger.",
      "Press Save and confirm. That plans the work orders and reserves free yarn in one transaction.",
    ],
    check: async (s) => {
      const r = await api<Paged<{ id: number; code: string; status: string; created_at: string }>>("/orders?limit=5");
      const mine = r.items.filter((o) => since(s, o.created_at));
      const hit = mine.find((o) => o.status === "confirmed");
      if (hit) return { done: true, detail: `${hit.code} confirmed`, vars: { orderId: hit.id, orderCode: hit.code } };
      if (mine.length) return { done: false, detail: `${mine[0].code} is a ${mine[0].status}: confirm it from Orders` };
      return { done: false, detail: "Waiting for a new confirmed order" };
    },
  },
  {
    id: "issue",
    needs: "orderId",
    scene: "Scene 1 → 2 · Hand-off",
    role: "store",
    title: "Issue the yarn to the floor",
    path: () => "/store",
    target: () => "[data-tour=needs-yarn]",
    body: (v) => [
      `${v.orderCode ?? "The order"} is now on the Needs yarn list. Press Issue, check the reserved lots it suggests, and press Issue to floor.`,
      "That is the only hand-off a person makes: once the yarn is on the floor, the job goes to the least busy working loom and starts by itself.",
    ],
    check: async (s) => {
      const [first] = await mains(s.vars.orderId!);
      if (!first) return { done: false };
      return { done: first.status !== "waiting", detail: first.status === "waiting" ? `${first.code} waiting for yarn` : `${first.code} is ${first.status}` };
    },
  },
  {
    id: "floor",
    needs: "orderId",
    scene: "Scene 2 · Production floor",
    role: "supervisor",
    title: "The loom picked it up",
    path: () => "/floor",
    target: (v) => (v.loom ? `[data-machine="${v.loom}"]` : ""),
    body: (v) => [
      `Nobody queued ${v.orderCode ?? "the order"}: it went to the least busy loom and started. The machine feed counts the metres every few seconds, no reload.`,
      "Tap the tile for its timeline: running, idle and breakdown time, output by hour.",
    ],
    check: async (s) => {
      const board = await api<{ machines: Tile[] }>("/production/board");
      const tile = board.machines.find((m) => m.job?.order_id === s.vars.orderId && m.job?.stage !== "dyeing");
      if (tile?.job) {
        const line = `${tile.code} · ${tile.job.stage} ${metres(tile.job.produced)} of ${metres(tile.job.planned)}`;
        return { done: tile.job.status === "running", detail: line, vars: { loom: tile.code } };
      }
      const [first] = await mains(s.vars.orderId!);
      if (first?.status === "queued") return { done: false, detail: `${first.code} is number ${first.queue_position} in a busy loom's queue. Move it to a free loom from Work orders.` };
      if (first?.status === "done") return { done: true, detail: `${first.code} already done` };
      return { done: false, detail: "Waiting for the job to start" };
    },
  },
  {
    id: "breakdown",
    scene: "Scene 2 · Production floor",
    role: "supervisor",
    title: "A loom breaks down",
    path: () => "/floor",
    body: (v) => [
      `Pick a running loom other than ${v.loom ?? "ours"}. Press Breakdown, choose a reason, save. Its tile turns red at once on every screen, and its job pauses.`,
      "Press Running to repair it: the job resumes and the downtime stays on record with its reason.",
    ],
  },
  {
    id: "crew",
    scene: "Scene 2 · Production floor",
    role: "supervisor",
    title: "Who is on which machine",
    path: () => "/floor/crew",
    body: () => [
      "Search a worker (try Ramesh), assign them to a loom. That writes their attendance for the shift: wages at month end come from this sheet.",
      "A worker on a machine can't be marked absent.",
    ],
  },
  {
    id: "rolls",
    needs: "orderId",
    scene: "Scene 2 → 3 · Rolls flow",
    role: "supervisor",
    title: "Rolls come off the loom",
    path: () => "/floor",
    body: () => [
      "Every ~60 m the loom cuts a roll with its own ID, tied to the order, loom, shift and yarn lots.",
      "At plan the loom cuts the tail roll and the job finishes by itself. The dye job then goes onto a free dye range and dyes the lot; dyed rolls join the QC queue.",
      "This takes a few minutes at live speed.",
    ],
    check: async (s) => {
      const [{ count }, line] = await Promise.all([rolls(s.vars.orderId!), progressLine(s.vars.orderId!)]);
      return { done: count("awaiting_qc", "passed", "rework", "rejected", "dispatched") > 0, detail: line };
    },
  },
  {
    id: "qc",
    needs: "orderId",
    scene: "Scene 3 · Quality check",
    role: "qc",
    title: "Check every roll",
    path: () => "/qc",
    target: () => "[data-tour=qc-queue]",
    body: (v) => [
      `Open each roll of ${v.orderCode ?? "the order"}, record defects (4-point system), and press Pass with shade band A.`,
      "Rework sends the roll back to the dye range by itself; the third check must pass or reject. Keep going until the floor is finished and the queue is empty.",
    ],
    check: async (s) => {
      const [{ items, count }, jobs, line] = await Promise.all([rolls(s.vars.orderId!), mains(s.vars.orderId!), progressLine(s.vars.orderId!)]);
      const floorDone = jobs.length > 0 && jobs.every((j) => j.status === "done");
      const open = count("in_process", "awaiting_qc", "rework");
      const passed = items.find((r) => r.status === "passed" || r.status === "dispatched");
      const detail = `${count("awaiting_qc")} waiting · ${count("passed")} passed · ${count("rework")} rework · ${count("rejected")} rejected${floorDone ? "" : ` · ${line}`}`;
      return { done: floorDone && open === 0 && !!passed, detail, vars: passed ? { rollId: passed.id } : undefined };
    },
  },
  {
    id: "trace",
    scene: "Scene 3 · Quality check",
    role: "qc",
    title: "Where did this roll come from?",
    path: (v) => (v.rollId ? `/qc/rolls/${v.rollId}` : "/qc"),
    body: () => [
      "The roll's trace: which yarn lots and suppliers went into it, which loom and shift wove it, every check and rework.",
      "A bad supplier lot shows up here and on Insights as a pattern, not a guess.",
    ],
  },
  {
    id: "buyer",
    scene: "Scene 4 · The buyer asks",
    role: "accounts",
    title: "“Where is my order?”",
    path: (v) => (v.orderId ? `/orders/${v.orderId}` : "/orders"),
    target: () => "[data-tour=buyer-link]",
    body: () => [
      "The stage here comes from the data: yarn, metres woven and dyed, rolls passed. Nobody types “in production”.",
      "Copy the buyer link and open it in a new tab: the buyer sees the same stage, with no login.",
    ],
  },
  {
    id: "truck",
    needs: "orderId",
    scene: "Scene 5 · Dispatch",
    role: "dispatch",
    title: "Load the truck",
    path: (v) => (v.truckId ? `/dispatch/${v.truckId}` : "/stock/finished"),
    target: () => "[data-tour=truck-scan]",
    body: (v) => [
      `A draft truck${v.truckCode ? ` (${v.truckCode})` : ""} was made when the first roll passed. Scan each roll or press Load, enter vehicle KA-01-AB-1234, and press Confirm dispatch.`,
      "Try loading a roll twice: refused, a roll can never leave twice. Mixed shade bands need a supervisor.",
      "Confirming makes the invoice from the rolls on the truck.",
    ],
    check: async (s) => {
      const r = await api<Paged<{ id: number; code: string; status: string; roll_count: number; metres: string }>>(`/dispatch/dispatches?order_id=${s.vars.orderId}&limit=20`);
      const sent = r.items.find((d) => d.status === "confirmed");
      if (sent) return { done: true, detail: `${sent.code} left with ${sent.roll_count} rolls, ${metres(sent.metres)}`, vars: { truckId: sent.id, truckCode: sent.code } };
      const draft = r.items[0];
      if (draft) return { done: false, detail: `${draft.code}: ${draft.roll_count} rolls loaded`, vars: { truckId: draft.id, truckCode: draft.code } };
      return { done: false, detail: "No truck yet: start one from Finished stock" };
    },
  },
  {
    id: "closed",
    needs: "orderId",
    scene: "Scene 5 · Dispatch",
    role: "accounts",
    title: "The order closes itself",
    path: () => "/orders",
    body: (v) => [
      `The last truck closed ${v.orderCode ?? "the order"} on its own: shipped within 2% of the order. Its leftover reserved yarn went back to orders that need it.`,
      "If rejects left it short, it stays open: press Close and give the reason.",
    ],
    check: async (s) => {
      const o = await api<{ status: string; qty_m: string }>(`/orders/${s.vars.orderId}`);
      return { done: o.status === "closed", detail: o.status === "closed" ? "Closed" : `Still ${o.status}: close it short with a reason` };
    },
  },
  {
    id: "payment",
    needs: "orderId",
    scene: "Scene 6 · Month-end",
    role: "accounts",
    title: "The buyer pays",
    path: () => "/finance/payments",
    body: (v) => [
      `The invoice for ${v.orderCode ?? "the order"} matches the rolls on the truck, metre for metre, at the order rate. Find it under Invoices.`,
      "Record the buyer's payment against it here.",
    ],
    check: async (s) => {
      const r = await api<Paged<{ code: string; status: string; outstanding_paise: number }>>(`/finance/invoices?order_id=${s.vars.orderId}&limit=10`);
      const inv = r.items[0];
      if (!inv) return { done: false, detail: "No invoice yet" };
      return { done: inv.status !== "issued", detail: `${inv.code} ${inv.status.replace("_", " ")}` };
    },
  },
  {
    id: "month",
    scene: "Scene 6 · Month-end",
    role: "accounts",
    title: "Close the books",
    path: () => "/finance/month",
    body: (v) => [
      `Cost per order is yarn (by lot, at its price) + labour (from attendance) + machine hours, with the rule printed on screen. Find ${v.orderCode ?? "the order"}.`,
      "Profit puts invoices and payments against yarn bills, wages and expenses. Wages are under Wages, built from the crew sheet.",
    ],
  },
  {
    id: "end",
    scene: "Close · Owner",
    role: "owner",
    title: "Back where we started",
    path: () => "/owner",
    body: (v) => [
      `${v.orderCode ?? "The order"} went from a truck of yarn to a paid invoice. The only things people did were the decisions: receive, approve, issue, inspect, load, get paid.`,
      "Everything between (queueing, starting, finishing stages, closing the order, reserving yarn) the mill did by itself, and every step is in the audit log.",
    ],
  },
];
