from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.codes import next_code
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.core.units import line_amount_paise, qty
from app.modules.auth.models import User
from app.modules.inventory.labels import format_label, parse_label
from app.modules.inventory.models import (
    BatchStatus,
    ExpectedDelivery,
    ExpectedDeliveryStatus,
    MoveReason,
    Receipt,
    ReceiptStatus,
    YarnBatch,
)
from app.modules.inventory.service import (
    EXPECTED_DELIVERY_TRANSITIONS,
    RECEIPT_TRANSITIONS,
    delivery_received_kg,
    find_item,
    item_label,
    move_yarn,
)
from app.modules.masters.models import LocationKind, Supplier, YarnItem
from app.modules.orders.models import Order, OrderStatus

# cotton picks up or loses moisture in transit, so small weight gaps are not shortages.
# ponytail: one mill-wide value until yarn_items.qty_tolerance_pct lands (docs/schema-requests.md)
QTY_TOLERANCE_PCT = Decimal(2)
OPEN = (ExpectedDeliveryStatus.open, ExpectedDeliveryStatus.partially_received)


def variance_pct(expected: Decimal, actual: Decimal) -> Decimal:
    return (abs(actual - expected) / expected * 100).quantize(Decimal("0.01"))


def outside_tolerance(expected: Decimal, actual: Decimal) -> bool:
    return variance_pct(expected, actual) > QTY_TOLERANCE_PCT


# ---------------------------------------------------------------- expected deliveries


def delivery_row(db: Session, d: ExpectedDelivery) -> dict:
    received = delivery_received_kg(db, d.id)
    order = db.get(Order, d.order_id) if d.order_id else None
    return {
        "id": d.id,
        "supplier_id": d.supplier_id,
        "supplier_code": d.supplier.code,
        "supplier_name": d.supplier.name,
        "yarn_item_id": d.yarn_item_id,
        "label": item_label(d.yarn_item),
        "expected_kg": d.expected_kg,
        "received_kg": received,
        "rate_paise_per_kg": d.rate_paise_per_kg,
        "order_id": d.order_id,
        "order_code": order.code if order else None,
        "expected_date": d.expected_date,
        "status": d.status,
        "created_at": d.created_at,
    }


def list_deliveries(
    db: Session, page: Page, status: ExpectedDeliveryStatus | None, open_only: bool
) -> dict:
    stmt = select(ExpectedDelivery).order_by(ExpectedDelivery.expected_date, ExpectedDelivery.id)
    if status:
        stmt = stmt.where(ExpectedDelivery.status == status)
    if open_only:
        stmt = stmt.where(ExpectedDelivery.status.in_(OPEN))
    result = paginate(db, stmt, page)
    return {"items": [delivery_row(db, d) for d in result["items"]], "total": result["total"]}


def create_delivery(db: Session, user: User, data) -> dict:
    supplier = db.get(Supplier, data.supplier_id)
    if not supplier or not supplier.active:
        raise NotFound("Supplier not found or inactive", field="supplier_id")
    item = db.get(YarnItem, data.yarn_item_id)
    if not item or not item.active:
        raise NotFound("Yarn item not found or inactive", field="yarn_item_id")
    if data.order_id:
        order = db.get(Order, data.order_id)
        if not order:
            raise NotFound("Order not found", field="order_id")
        if order.status not in (OrderStatus.draft, OrderStatus.confirmed):
            raise Conflict(f"Order {order.code} is {order.status}", field="order_id")
    d = ExpectedDelivery(
        supplier_id=supplier.id,
        yarn_item_id=item.id,
        expected_kg=qty(data.expected_kg),
        rate_paise_per_kg=data.rate_paise_per_kg,
        order_id=data.order_id,
        expected_date=data.expected_date,
    )
    db.add(d)
    db.flush()
    audit.record(
        db, user.id, "create", "expected_deliveries", d.id, data=data.model_dump(mode="json")
    )
    db.commit()
    events.publish("stock", {"type": "expected_delivery", "id": d.id})
    return delivery_row(db, db.get(ExpectedDelivery, d.id))


def cancel_delivery(db: Session, user: User, delivery_id: int, reason: str) -> dict:
    d = db.get(ExpectedDelivery, delivery_id)
    if not d:
        raise NotFound(f"Expected delivery {delivery_id} not found")
    check_transition(EXPECTED_DELIVERY_TRANSITIONS, d.status, ExpectedDeliveryStatus.cancelled)
    d.status = ExpectedDeliveryStatus.cancelled
    audit.record(db, user.id, "cancel", "expected_deliveries", d.id, reason=reason)
    db.commit()
    events.publish("stock", {"type": "expected_delivery", "id": d.id})
    return delivery_row(db, d)


# demo labels: one correct label and one with the wrong colour, per open delivery
def sample_labels(db: Session) -> list[dict]:
    out = []
    for d in db.scalars(
        select(ExpectedDelivery)
        .where(ExpectedDelivery.status.in_(OPEN))
        .order_by(ExpectedDelivery.id)
    ):
        item, sup = d.yarn_item, d.supplier
        lot = f"{sup.code}-L{d.id:04d}"
        kg = qty(d.expected_kg - delivery_received_kg(db, d.id))
        wrong = "Black" if item.colour != "Black" else "Navy"
        base = {"delivery_id": d.id, "supplier": sup.name, "kg": kg}
        out.append(
            {
                **base,
                "kind": "match",
                "title": f"{item_label(item)} · lot {lot}",
                "payload": format_label(sup.code, lot, item.fibre, item.count, item.colour, kg),
            }
        )
        out.append(
            {
                **base,
                "kind": "wrong_colour",
                "title": f"WRONG COLOUR test · lot {lot}X",
                "payload": format_label(sup.code, f"{lot}X", item.fibre, item.count, wrong, kg),
            }
        )
    return out + _walk_in_labels(db)


WALK_IN_KG = Decimal(500)


# demo: yarn that arrives with no request first. One label per yarn item, from the supplier that
# last sent it (else the first supplier); a new lot code each day so a re-run makes a new lot
def _walk_in_labels(db: Session) -> list[dict]:
    suppliers = db.scalars(select(Supplier).where(Supplier.active).order_by(Supplier.id)).all()
    if not suppliers:
        return []
    last_from = dict(
        db.execute(
            select(YarnBatch.yarn_item_id, YarnBatch.supplier_id)
            .where(YarnBatch.yarn_item_id.is_not(None))
            .order_by(YarnBatch.id)
        ).all()
    )
    by_id = {s.id: s for s in suppliers}
    day = datetime.now(UTC).strftime("%y%m%d")
    out = []
    for item in db.scalars(select(YarnItem).where(YarnItem.active).order_by(YarnItem.id)):
        sup = by_id.get(last_from.get(item.id)) or suppliers[0]
        lot = f"{sup.code}-W{day}{item.id:02d}"
        out.append(
            {
                "delivery_id": None,
                "supplier": sup.name,
                "kg": qty(WALK_IN_KG),
                "kind": "walk_in",
                "title": f"{item_label(item)} · lot {lot}",
                "payload": format_label(
                    sup.code, lot, item.fibre, item.count, item.colour, qty(WALK_IN_KG)
                ),
            }
        )
    return out


# ---------------------------------------------------------------- scan check (no writes)


# expected vs actual for one scanned label. Read-only: the screen shows it before anything is saved
def check_label(db: Session, payload: str, expected_delivery_id: int | None) -> dict:
    label = parse_label(payload)
    supplier = db.scalar(select(Supplier).where(Supplier.code == label["supplier_code"]))
    if not supplier:
        raise Unprocessable(f"Unknown supplier code {label['supplier_code']}", field="payload")
    delivery = _pick_delivery(db, supplier.id, label, expected_delivery_id)
    return {
        "label": label,
        "supplier": {"id": supplier.id, "code": supplier.code, "name": supplier.name},
        "delivery": delivery_row(db, delivery) if delivery else None,
        "comparison": compare(db, delivery, label, label["label_kg"]),
        "suggested_rate_paise_per_kg": None if delivery else _last_rate(db, supplier.id, label),
    }


# no request to price the lot: offer this supplier's last GRN rate for the yarn, else any supplier's
def _last_rate(db: Session, supplier_id: int, label: dict) -> int | None:
    item = find_item(db, label["fibre"], label["count"], label["colour"])
    if not item:
        return None
    stmt = select(YarnBatch.unit_cost_paise_per_kg).where(YarnBatch.yarn_item_id == item.id)
    own = db.scalar(stmt.where(YarnBatch.supplier_id == supplier_id).order_by(YarnBatch.id.desc()))
    return own or db.scalar(stmt.order_by(YarnBatch.id.desc()))


def _pick_delivery(db, supplier_id, label, delivery_id) -> ExpectedDelivery | None:
    if delivery_id:
        d = db.get(ExpectedDelivery, delivery_id)
        if not d or d.supplier_id != supplier_id:
            raise Unprocessable("That delivery is not from this supplier", field="payload")
        return d
    open_ones = db.scalars(
        select(ExpectedDelivery)
        .where(ExpectedDelivery.supplier_id == supplier_id, ExpectedDelivery.status.in_(OPEN))
        .order_by(ExpectedDelivery.expected_date, ExpectedDelivery.id)
    ).all()
    item = find_item(db, label["fibre"], label["count"], label["colour"])
    exact = [d for d in open_ones if item and d.yarn_item_id == item.id]
    return (exact or open_ones or [None])[0]


# one row per checked field; spec mismatch quarantines, weight gap only flags
def compare(db: Session, delivery, label: dict, received_kg: Decimal) -> list[dict]:
    rows = []
    if delivery:
        exp = delivery.yarn_item
        for field, want in (("fibre", exp.fibre), ("count", exp.count), ("colour", exp.colour)):
            got = label[field]
            rows.append(
                {
                    "field": field,
                    "expected": want,
                    "actual": got,
                    "ok": want.strip().lower() == got.strip().lower(),
                    "blocks": True,
                }
            )
        left = qty(delivery.expected_kg - delivery_received_kg(db, delivery.id))
        rows.append(
            {
                "field": "delivery_kg",
                "expected": str(left),
                "actual": str(label["label_kg"]),
                "ok": label["label_kg"] <= left or not outside_tolerance(left, label["label_kg"]),
                "blocks": False,
            }
        )
    rows.append(
        {
            "field": "weighed_kg",
            "expected": str(label["label_kg"]),
            "actual": str(received_kg),
            "ok": not outside_tolerance(label["label_kg"], received_kg),
            "blocks": False,
        }
    )
    return rows


# ---------------------------------------------------------------- receipts


def receipt_row(db: Session, r: Receipt) -> dict:
    batches = db.scalars(
        select(YarnBatch).where(YarnBatch.receipt_id == r.id).order_by(YarnBatch.id)
    ).all()
    d = db.get(ExpectedDelivery, r.expected_delivery_id) if r.expected_delivery_id else None
    return {
        "id": r.id,
        "code": r.code,
        "supplier_id": r.supplier_id,
        "supplier_name": r.supplier.name,
        "expected_delivery": delivery_row(db, d) if d else None,
        "vehicle_no": r.vehicle_no,
        "bill_no": r.bill_no,
        "bill_amount_paise": r.bill_amount_paise,
        "status": r.status,
        "confirmed_at": r.confirmed_at,
        "created_at": r.created_at,
        "batches": batches,
        "total_kg": qty(sum((b.received_kg for b in batches), Decimal(0))),
    }


def list_receipts(db: Session, page: Page, status: ReceiptStatus | None) -> dict:
    stmt = select(Receipt).order_by(Receipt.id.desc())
    if status:
        stmt = stmt.where(Receipt.status == status)
    result = paginate(db, stmt, page)
    return {"items": [receipt_row(db, r) for r in result["items"]], "total": result["total"]}


def get_receipt(db: Session, receipt_id: int) -> dict:
    r = db.get(Receipt, receipt_id)
    if not r:
        raise NotFound(f"Receipt {receipt_id} not found")
    return receipt_row(db, r)


def create_receipt(db: Session, user: User, data) -> dict:
    supplier_id = data.supplier_id
    if data.expected_delivery_id:
        d = db.get(ExpectedDelivery, data.expected_delivery_id)
        if not d:
            raise NotFound("Expected delivery not found", field="expected_delivery_id")
        if d.status not in OPEN:
            raise Conflict(f"Delivery is already {d.status}", field="expected_delivery_id")
        if supplier_id and supplier_id != d.supplier_id:
            raise Unprocessable("Delivery is from another supplier", field="supplier_id")
        supplier_id = d.supplier_id
    supplier = db.get(Supplier, supplier_id) if supplier_id else None
    if not supplier or not supplier.active:
        raise NotFound("Supplier not found or inactive", field="supplier_id")
    r = Receipt(
        code=next_code(db, "RC"),
        supplier_id=supplier.id,
        expected_delivery_id=data.expected_delivery_id,
        vehicle_no=data.vehicle_no,
        bill_no=data.bill_no,
    )
    db.add(r)
    db.flush()
    audit.record(db, user.id, "create", "receipts", r.id)
    db.commit()
    return receipt_row(db, db.get(Receipt, r.id))


def _draft_receipt(db: Session, receipt_id: int) -> Receipt:
    locked = db.scalar(select(Receipt.id).where(Receipt.id == receipt_id).with_for_update())
    if locked is None:
        raise NotFound(f"Receipt {receipt_id} not found")
    r = db.get(Receipt, receipt_id, populate_existing=True)
    if r.status != ReceiptStatus.draft:
        raise Conflict(f"Receipt {r.code} is already confirmed", field="status")
    return r


# one lot off the truck. Rescanning the same lot on the same receipt returns the first batch.
def add_line(db: Session, user: User, receipt_id: int, data) -> dict:
    r = _draft_receipt(db, receipt_id)
    delivery = db.get(ExpectedDelivery, r.expected_delivery_id) if r.expected_delivery_id else None
    rate = delivery.rate_paise_per_kg if delivery else data.rate_paise_per_kg
    if rate is None:
        raise Unprocessable("No expected delivery on this receipt: give the rate", field="rate")

    if data.label_missing:
        batch = YarnBatch(
            code=next_code(db, "YB"),
            supplier_id=r.supplier_id,
            receipt_id=r.id,
            received_kg=qty(data.received_kg),
            unit_cost_paise_per_kg=rate,
            status=BatchStatus.pending_identification,
            order_id=delivery.order_id if delivery else None,
            mismatch_notes="Label missing or unreadable",
        )
        db.add(batch)
        db.flush()
        audit.record(db, user.id, "receive", "yarn_batches", batch.id, data={"label": None})
        db.commit()
        events.publish("stock", {"type": "receive_line", "id": batch.id})
        return {"batch": batch, "created": True, "comparison": []}

    label = parse_label(data.payload) if data.payload else data.label_fields()
    supplier = db.get(Supplier, r.supplier_id)
    if label.get("supplier_code", supplier.code) != supplier.code:
        raise Unprocessable(
            f"Label is from {label['supplier_code']}, this truck is from {supplier.code}",
            field="payload",
        )
    existing = db.scalar(
        select(YarnBatch).where(
            YarnBatch.supplier_id == r.supplier_id,
            YarnBatch.supplier_lot == label["supplier_lot"],
            YarnBatch.receipt_id == r.id,
        )
    )
    if existing:
        return {"batch": existing, "created": False, "comparison": []}

    comparison = compare(db, delivery, label, data.received_kg)
    item = find_item(db, label["fibre"], label["count"], label["colour"])
    if item is None and delivery is None:
        raise Unprocessable(
            f"No yarn item {label['fibre']} {label['count']} {label['colour']} in masters",
            field="fibre",
        )
    spec_bad = [c for c in comparison if c["blocks"] and not c["ok"]]
    notes = [f"{c['field']}: expected {c['expected']}, label says {c['actual']}" for c in spec_bad]
    if item is None:
        notes.append("Label yarn is not in masters")
    weight = next(c for c in comparison if c["field"] == "weighed_kg")
    if not weight["ok"]:
        pct = variance_pct(label["label_kg"], data.received_kg)
        notes.append(
            f"Weight: label {label['label_kg']} kg, weighed {data.received_kg} kg "
            f"({pct}% > {QTY_TOLERANCE_PCT}% tolerance)"
        )
    quarantine = bool(spec_bad) or item is None
    batch = YarnBatch(
        code=next_code(db, "YB"),
        # unknown yarn is held against the item we expected, so the constraint holds
        yarn_item_id=item.id if item else delivery.yarn_item_id,
        supplier_id=r.supplier_id,
        supplier_lot=label["supplier_lot"],
        receipt_id=r.id,
        received_kg=qty(data.received_kg),
        unit_cost_paise_per_kg=rate,
        status=BatchStatus.quarantined if quarantine else BatchStatus.inspection,
        order_id=delivery.order_id if delivery else None,
        mismatch_notes="; ".join(notes) or None,
    )
    db.add(batch)
    db.flush()
    audit.record(
        db,
        user.id,
        "receive",
        "yarn_batches",
        batch.id,
        data={
            "label_kg": str(label["label_kg"]),
            "received_kg": str(data.received_kg),
            "mismatches": [c["field"] for c in comparison if not c["ok"]],
        },
    )
    db.commit()
    events.publish("stock", {"type": "receive_line", "id": batch.id})
    return {"batch": batch, "created": True, "comparison": comparison}


# truck done: every lot moves supplier -> inspection (or quarantine), bill stored, all or nothing
def confirm_receipt(db: Session, user: User, receipt_id: int) -> dict:
    r = _draft_receipt(db, receipt_id)
    batches = db.scalars(select(YarnBatch).where(YarnBatch.receipt_id == r.id)).all()
    if not batches:
        raise Conflict("Add at least one lot before confirming", field="batches")
    check_transition(RECEIPT_TRANSITIONS, r.status, ReceiptStatus.confirmed)
    for b in batches:
        to = (
            LocationKind.quarantine
            if b.status == BatchStatus.quarantined
            else LocationKind.inspection
        )
        move_yarn(
            db,
            b,
            b.received_kg,
            LocationKind.supplier,
            to,
            MoveReason.receipt,
            user.id,
            ref=("receipt", r.id),
        )
    r.bill_amount_paise = sum(
        line_amount_paise(b.unit_cost_paise_per_kg, b.received_kg) for b in batches
    )
    r.status = ReceiptStatus.confirmed
    r.confirmed_at = datetime.now(UTC)
    db.flush()

    if r.expected_delivery_id:
        d = db.get(ExpectedDelivery, r.expected_delivery_id)
        got = delivery_received_kg(db, d.id)
        short = got < d.expected_kg and outside_tolerance(d.expected_kg, got)
        new = (
            ExpectedDeliveryStatus.partially_received if short else ExpectedDeliveryStatus.received
        )
        if new != d.status:
            check_transition(EXPECTED_DELIVERY_TRANSITIONS, d.status, new)
            d.status = new
            audit.record(db, user.id, str(new), "expected_deliveries", d.id, data={"kg": str(got)})
    audit.record(
        db,
        user.id,
        "confirm",
        "receipts",
        r.id,
        data={"lots": len(batches), "bill_amount_paise": r.bill_amount_paise},
    )
    db.commit()
    events.publish("stock", {"type": "receipt_confirmed", "id": r.id})
    return receipt_row(db, r)
