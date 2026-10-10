import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

type Meaning = "neutral" | "info" | "success" | "warning" | "danger";

// one colour per meaning, same everywhere: grey = not started, blue = moving,
// green = good/finished, amber = needs attention, red = stopped/failed
const MEANING: Record<string, Meaning> = {
  draft: "neutral", waiting: "neutral", open: "neutral", off: "neutral", idle: "neutral",
  pending_identification: "neutral", issued: "neutral", cancelled: "neutral", closed: "neutral",
  released: "neutral", info: "info",

  queued: "info", running: "info", inspection: "info", in_process: "info", awaiting_qc: "info",
  loading: "info", active: "info", acknowledged: "info", partially_received: "info",

  confirmed: "success", approved: "success", passed: "success", pass: "success", done: "success",
  dispatched: "success", paid: "success", received: "success", present: "success",
  final: "success", resolved: "success", consumed: "success",

  paused: "warning", quarantined: "warning", rework: "warning", maintenance: "warning",
  part_paid: "warning", half_day: "warning", warn: "warning",

  rejected: "danger", reject: "danger", breakdown: "danger", absent: "danger", critical: "danger",
};

const STYLE: Record<Meaning, string> = {
  neutral: "bg-neutral-soft text-neutral",
  info: "bg-info-soft text-info",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
};

// statuses that mean "happening right now" get a soft pulse
const LIVE = new Set(["running", "in_process", "loading"]);

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const meaning = MEANING[status] ?? "neutral";
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[0.8rem] leading-none font-semibold whitespace-nowrap", STYLE[meaning], className)}>
      <span className={cn("size-2 rounded-full bg-current", LIVE.has(status) && "live-dot")} aria-hidden />
      {humanize(status)}
    </span>
  );
}
