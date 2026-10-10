import io
from decimal import Decimal, InvalidOperation

import segno

from app.core.errors import Unprocessable

# supplier label QR payload, agreed with the evaluator (docs/assumptions.md):
#   SUP=KSM;LOT=KSM-L2291;FIB=Cotton;CNT=Ne 40/1;COL=Raw White;KG=1200
LABEL_KEYS = {
    "SUP": "supplier_code",
    "LOT": "supplier_lot",
    "FIB": "fibre",
    "CNT": "count",
    "COL": "colour",
    "KG": "label_kg",
}
MAX_PAYLOAD = 300


# scanned string -> dict; any missing or broken key is a 422 on the payload field
def parse_label(payload: str) -> dict:
    text = payload.strip()
    if not text:
        raise Unprocessable("Scan is empty", field="payload")
    if len(text) > MAX_PAYLOAD:
        raise Unprocessable("Scan is too long to be a supplier label", field="payload")
    found = {}
    for part in text.split(";"):
        key, sep, value = part.partition("=")
        key, value = key.strip().upper(), value.strip()
        if sep and key in LABEL_KEYS and value:
            found[LABEL_KEYS[key]] = value
    missing = [k for k, name in LABEL_KEYS.items() if name not in found]
    if missing:
        raise Unprocessable(
            f"Label unreadable, missing {', '.join(missing)}. Enter by hand or mark label missing.",
            field="payload",
        )
    try:
        kg = Decimal(found["label_kg"])
    except InvalidOperation:
        kg = Decimal(0)
    if not kg.is_finite() or kg <= 0 or kg > Decimal("1000000"):
        raise Unprocessable("Label KG must be a positive number", field="payload")
    found["label_kg"] = kg.quantize(Decimal("0.001"))
    found["supplier_code"] = found["supplier_code"].upper()
    return found


def format_label(supplier_code: str, lot: str, fibre: str, count: str, colour: str, kg) -> str:
    return f"SUP={supplier_code};LOT={lot};FIB={fibre};CNT={count};COL={colour};KG={kg}"


def qr_svg(data: str) -> bytes:
    out = io.BytesIO()
    segno.make(data, error="m").save(out, kind="svg", scale=4, border=2, xmldecl=False)
    return out.getvalue()
