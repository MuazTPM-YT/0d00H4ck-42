import json
import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

# Explainer layer. Today: fixed sentence templates filled from an insight's facts.
# A local model can replace narrate() later; numbers_ok() is the guard it must pass.

NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(n).normalize() for n in NUMBER.findall(text.replace(",", ""))}


# every number in the sentence must be a number in the facts (record links do not count)
def numbers_ok(text: str, facts: dict) -> bool:
    cited = {k: v for k, v in facts.items() if k != "records"}
    return _numbers(text) <= _numbers(json.dumps(cited))


def supplier_text(f: dict) -> str:
    if f["key"].startswith("gate_"):
        return (
            f"{f['count']} of {f['batches']} {f['supplier']} batches were {f['metric']} at the "
            f"gate ({f['rate_pct']}%), against {f['others_rate_pct']}% for other suppliers. "
            "Raise it with the supplier before the next order."
        )
    return (
        f"{f['defective']} of {f['rolls']} rolls woven with {f['supplier']} yarn had "
        f"{f['defect']} at first QC ({f['rate_pct']}%). On the same {f['looms']} looms, other "
        f"suppliers' yarn would give about {f['expected']} such rolls, so {f['supplier']} runs "
        f"{f['lift']}x higher. The rolls and yarn lots behind this are listed below."
    )


def root_cause_text(f: dict) -> str:
    top = f["causes"][0]
    text = (
        f"Defective rolls rose to {f['rate_pct']}% in the last {f['window_days']} days, "
        f"from {f['baseline_rate_pct']}% before: about {f['excess']} extra. "
        f"The {top['factor']} {top['value']} explains {top['share_pct']}% of the extra, "
        f"with {top['defective']} of its {top['rolls']} rolls defective."
    )
    if len(f["causes"]) > 1:
        nxt = f["causes"][1]
        text += f" Next: {nxt['factor']} {nxt['value']} ({nxt['share_pct']}%)."
    return text


# "2026-09-28" or a timestamp -> "28 Sep" (day and month only, so no new numbers appear)
def day(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {d:%b}"


def slowdown_text(f: dict) -> str:
    text = (
        f"{f['machine']} made {f['drop_pct']}% less per running hour for {f['days']} days in a "
        f"row ({day(f['from'])} to {day(f['to'])}): down to {f['low_per_hour']} {f['unit']} "
        f"against its usual {f['baseline_per_hour']} {f['unit']}."
    )
    if f["followed_by"]:
        text += (
            f" It then broke down on {day(f['followed_by']['at'])}: {f['followed_by']['reason']}."
        )
    else:
        text += " A slow, steady drop like this often comes before a breakdown: plan a check."
    return text


def cluster_text(f: dict) -> str:
    return (
        f"{f['name']} had {f['count']} breakdowns in the last {f['days']} days, "
        f"{f['downtime_hours']} hours of downtime. Most common reason: {f['top_reason']} "
        f"({f['top_reason_count']} times)."
    )


def idle_text(f: dict) -> str:
    return (
        f"When shift {f['from_shift']} hands over to shift {f['to_shift']} at {f['at']}, machines "
        f"stand idle for {f['median_min']} min (median of {f['spells']} stops over {f['days']} "
        f"days). Other handovers take {f['others_median_min']} min. That is about "
        f"{f['lost_hours']} machine-hours lost."
    )


def yield_text(f: dict) -> str:
    whose = "its jobs" if f["key"] == "machine" else "this order"
    return (
        f"{f['issued_kg']} kg of yarn went to {f['name']}, but the {f['metres']} m woven in "
        f"{whose} account for {f['expected_kg']} kg including normal process loss. "
        f"{f['gap_kg']} kg ({f['gap_pct']}%, about Rs {f['value_rupees']}) is unaccounted, "
        f"above the {f['tolerance_pct']}% tolerance. Check over-issues and floor waste."
    )


def impossible_text(f: dict) -> str:
    if f["check"] == "output_in_downtime":
        return (
            f"{f['qty']} {f['unit']} of output on {f['machine']} is stamped "
            f"{f['minutes_into_stop']} min into a {f['status']} ({f['reason']}), when the machine "
            "was stopped. Usually a counter that uploaded late or a wrong time: confirm the log."
        )
    if f["check"] == "roll_too_long":
        return (
            f"{f['roll']} ({f['length_m']} m) brings the fabric cut from {f['work_order']} to "
            f"{f['cut_total_m']} m, but only {f['logged_total_m']} m of output was logged on "
            f"{f['machine']} for it by then. Check the roll length or the missing output."
        )
    return (
        f"{f['batch']} came in at {f['kg']} kg, {f['ratio']}x what {f['supplier']} usually "
        f"sends ({f['usual_kg']} kg over {f['receipts']} receipts). Check for a typing mistake."
    )


TEMPLATES: dict[str, Callable[[dict], str]] = {
    "supplier_defects": supplier_text,
    "defect_root_cause": root_cause_text,
    "machine_slowdown": slowdown_text,
    "breakdown_cluster": cluster_text,
    "shift_change_idle": idle_text,
    "yarn_yield_gap": yield_text,
    "impossible_data": impossible_text,
}


def narrate(kind: str, facts: dict) -> str:
    return TEMPLATES[kind](facts)


# a role's morning summary, from its attention list (which already holds its open insights)
def briefing_text(items: list[dict]) -> str:
    if not items:
        return "Nothing needs you right now. New problems will show up here as they happen."
    urgent = sum(i["severity"] == "critical" for i in items)
    text = f"{len(items)} things need you today"
    text += f", {urgent} of them urgent. " if urgent else ". "
    text += f"Start with {items[0]['title']}"
    text += f" ({items[0]['detail']})." if items[0]["detail"] else "."
    if len(items) > 1:
        text += f" Then {items[1]['title']}."
    return text
