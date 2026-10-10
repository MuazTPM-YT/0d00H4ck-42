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


TEMPLATES: dict[str, Callable[[dict], str]] = {}


def narrate(kind: str, facts: dict) -> str:
    return TEMPLATES[kind](facts)
