import json
import re
from collections.abc import Callable
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


TEMPLATES: dict[str, Callable[[dict], str]] = {
    "supplier_defects": supplier_text,
    "defect_root_cause": root_cause_text,
}


def narrate(kind: str, facts: dict) -> str:
    return TEMPLATES[kind](facts)
