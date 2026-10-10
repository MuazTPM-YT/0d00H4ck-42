from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.codes import next_code
from app.core.enums import Unit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.idempotency import run_once
from app.core.pagination import Page
from app.core.states import check_transition
from app.core.units import qty
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.finance import service as finance
from app.modules.finance.models import Invoice
from app.modules.inventory import service as inventory
from app.modules.inventory.models import ItemKind, MoveReason, StockMove
from app.modules.masters.models import Buyer, FabricType, Location, LocationKind
from app.modules.orders import service as orders
from app.modules.orders.models import Order, OrderStatus
from app.modules.quality.models import Roll, RollStatus
from app.modules.quality.service import ROLL_TRANSITIONS

DISPATCH_TRANSITIONS = {
    DispatchStatus.draft: {DispatchStatus.loading},
    DispatchStatus.loading: {DispatchStatus.confirmed, DispatchStatus.draft},
}
# corner check: a passed roll older than this on the shelf needs a look
SHELF_DAYS = 7
# corner check: a truck open (draft or loading) longer than this is forgotten
STALE_TRUCK_HOURS = 12
# an order counts as fully shipped within this short fall (rolls never cut exact)
CLOSE_TOLERANCE = Decimal("0.02")
OPEN = (DispatchStatus.draft, DispatchStatus.loading)
ZERO = Decimal(0)


def _now() -> datetime:
    return datetime.now(UTC)


def _days_on_shelf(roll: Roll, now: datetime) -> int:
    return (now - roll.passed_at).days if roll.passed_at else 0


def _location_id(db: Session, kind: LocationKind) -> int:
    loc_id = db.scalar(select(Location.id).where(Location.kind == kind).order_by(Location.id))
    if not loc_id:
        raise Conflict(f"No '{kind}' location set up in masters")
    return loc_id


def _get(db: Session, dispatch_id: int, lock: bool = False) -> Dispatch:
    stmt = select(Dispatch).where(Dispatch.id == dispatch_id)
    d = db.scalar(stmt.with_for_update() if lock else stmt)
    if not d:
        raise NotFound(f"Dispatch {dispatch_id} not found")
    return d


# order row lock: a cancel or close waits for the truck, and the truck sees the new status
def _open_order(db: Session, order_id: int, field: str | None = None) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise NotFound(f"Order {order_id} not found", field=field)
    if order.status != OrderStatus.confirmed:
        raise Conflict(
            f"Order {order.code} is {order.status}, only confirmed orders ship",
            field=field,
            code="order_not_open",
        )
    return order


def _loaded(db: Session, dispatch_id: int, lock: bool = False) -> list[Roll]:
    stmt = (
        select(Roll)
        .join(DispatchRoll, DispatchRoll.roll_id == Roll.id)
        .where(DispatchRoll.dispatch_id == dispatch_id)
        .order_by(Roll.code)
    )
    return list(db.scalars(stmt.with_for_update(of=Roll) if lock else stmt))


# metres on this order's dispatches, split into shipped (confirmed) and open (draft/loading)
def _order_metres(db: Session, order_id: int, skip_dispatch: int | None = None) -> tuple:
    rows = db.execute(
        select(Dispatch.status, func.coalesce(func.sum(Roll.length_m), 0))
        .join(DispatchRoll, DispatchRoll.dispatch_id == Dispatch.id)
        .join(Roll, Roll.id == DispatchRoll.roll_id)
        .where(Dispatch.order_id == order_id, Dispatch.id != (skip_dispatch or 0))
        .group_by(Dispatch.status)
    ).all()
    shipped = sum((m for s, m in rows if s == DispatchStatus.confirmed), ZERO)
    open_m = sum((m for s, m in rows if s != DispatchStatus.confirmed), ZERO)
    return qty(shipped), qty(open_m)


def shipped_metres(db: Session, order_id: int) -> Decimal:
    return _order_metres(db, order_id)[0]


def _has_override(db: Session, dispatch_id: int) -> str | None:
    return db.scalar(
        select(audit.AuditLog.reason)
        .where(
            audit.AuditLog.entity_type == "dispatches",
            audit.AuditLog.entity_id == dispatch_id,
            audit.AuditLog.action == "shade_override",
        )
        .order_by(audit.AuditLog.id.desc())
    )


# --- roll picking (pure: no DB, easy to test and explain)


@dataclass
class Pick:
    band: str | None
    rolls: list
    total: Decimal
    need: Decimal

    @property
    def overshoot(self) -> Decimal:
        return max(self.total - self.need, ZERO)

    @property
    def short(self) -> Decimal:
        return max(self.need - self.total, ZERO)


# greedy subset-sum inside one band: biggest rolls that still fit, then the smallest roll that
# closes the gap. Every roll skipped in pass 1 overshoots, so any of them closes the gap.
def _pick_in_band(rolls: list, need: Decimal) -> list:
    chosen, rest, total = [], [], ZERO
    for r in sorted(rolls, key=lambda r: (-r.length_m, r.id)):
        if total + r.length_m <= need:
            chosen.append(r)
            total += r.length_m
        else:
            rest.append(r)
    if total < need and rest:
        chosen.append(min(rest, key=lambda r: (r.length_m, r.id)))
    return chosen


# one band where possible: covering band with least overshoot (then fewer rolls), else the
# band that gets closest
def pick_rolls(rolls: list, need: Decimal) -> Pick | None:
    if need <= 0 or not rolls:
        return None
    bands: dict[str | None, list] = defaultdict(list)
    for r in rolls:
        bands[r.shade_band].append(r)
    picks = []
    for band, in_band in bands.items():
        chosen = _pick_in_band(in_band, need)
        picks.append(Pick(band, chosen, sum((r.length_m for r in chosen), ZERO), need))
    covering = [p for p in picks if p.short == 0]
    if covering:
        return min(covering, key=lambda p: (p.overshoot, len(p.rolls), p.band or ""))
    return max(picks, key=lambda p: (p.total, p.band or ""))


# --- reads


def list_dispatches(
    db: Session,
    page: Page,
    status: DispatchStatus | None = None,
    order_id: int | None = None,
    buyer_id: int | None = None,
    vehicle: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    roll_stats = (
        select(
            DispatchRoll.dispatch_id,
            func.count().label("roll_count"),
            func.sum(Roll.length_m).label("metres"),
        )
        .join(Roll, Roll.id == DispatchRoll.roll_id)
        .group_by(DispatchRoll.dispatch_id)
        .subquery()
    )
    stmt = (
        select(
            Dispatch,
            Order.code,
            Buyer.name,
            func.coalesce(roll_stats.c.roll_count, 0),
            func.coalesce(roll_stats.c.metres, 0),
            Invoice.id,
            Invoice.code,
        )
        .join(Order, Order.id == Dispatch.order_id)
        .join(Buyer, Buyer.id == Dispatch.buyer_id)
        .outerjoin(roll_stats, roll_stats.c.dispatch_id == Dispatch.id)
        .outerjoin(Invoice, Invoice.dispatch_id == Dispatch.id)
    )
    if status:
        stmt = stmt.where(Dispatch.status == status)
    if order_id:
        stmt = stmt.where(Dispatch.order_id == order_id)
    if buyer_id:
        stmt = stmt.where(Dispatch.buyer_id == buyer_id)
    if vehicle:
        stmt = stmt.where(Dispatch.vehicle_no.ilike(f"%{vehicle.strip()}%"))
    when = func.coalesce(Dispatch.confirmed_at, Dispatch.created_at)
    if date_from:
        stmt = stmt.where(when >= datetime.combine(date_from, datetime.min.time(), UTC))
    if date_to:
        stmt = stmt.where(
            when < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), UTC)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(when.desc(), Dispatch.id.desc()).limit(page.limit).offset(page.offset)
    ).all()
    items = [
        {
            **{c: getattr(d, c) for c in ("id", "code", "order_id", "buyer_id", "vehicle_no")},
            **{c: getattr(d, c) for c in ("driver", "status", "confirmed_at", "created_at")},
            "order_code": order_code,
            "buyer_name": buyer_name,
            "roll_count": count,
            "metres": qty(metres),
            "invoice_id": inv_id,
            "invoice_code": inv_code,
        }
        for d, order_code, buyer_name, count, metres, inv_id, inv_code in rows
    ]
    return {"items": items, "total": total}


def _roll_row(r: Roll, loc_codes: dict[int, str]) -> dict:
    return {
        "id": r.id,
        "code": r.code,
        "length_m": r.length_m,
        "shade_band": r.shade_band,
        "location": loc_codes.get(r.location_id, "?"),
    }


def _location_codes(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Location.id, Location.code)).all())


def get_detail(db: Session, dispatch_id: int) -> dict:
    d = _get(db, dispatch_id)
    order = db.get(Order, d.order_id)
    buyer = db.get(Buyer, d.buyer_id)
    fabric = db.get(FabricType, order.fabric_type_id)
    locs = _location_codes(db)
    loaded = _loaded(db, d.id)
    loaded_m = qty(sum((r.length_m for r in loaded), ZERO))
    shipped, open_other = _order_metres(db, order.id, skip_dispatch=d.id)
    need = qty(order.qty_m - shipped - open_other - loaded_m)
    bands = sorted({r.shade_band for r in loaded if r.shade_band})

    proposal, candidates = None, []
    if d.status != DispatchStatus.confirmed:
        candidates = _free_rolls(db, order.id, bands[0] if len(bands) == 1 else None)
        pick = pick_rolls(candidates, need)
        if pick:
            proposal = {
                "band": pick.band,
                "roll_ids": [r.id for r in pick.rolls],
                "total_m": qty(pick.total),
                "need_m": qty(pick.need),
                "overshoot_m": qty(pick.overshoot),
                "short_m": qty(pick.short),
            }
    invoice = db.scalar(select(Invoice).where(Invoice.dispatch_id == d.id))
    return {
        **{c: getattr(d, c) for c in ("id", "code", "order_id", "buyer_id", "vehicle_no")},
        **{c: getattr(d, c) for c in ("driver", "status", "confirmed_at", "created_at")},
        "order_code": order.code,
        "buyer_name": buyer.name,
        "buyer_gstin": buyer.gstin,
        "buyer_city": buyer.city,
        "fabric": fabric.name,
        "colour": order.colour,
        "ordered_m": order.qty_m,
        "shipped_m": shipped,
        "remaining_m": max(need, ZERO),
        "loaded": [_roll_row(r, locs) for r in loaded],
        "loaded_m": loaded_m,
        "bands": bands,
        "shade_override": _has_override(db, d.id),
        "proposal": proposal,
        "candidates": [_roll_row(r, locs) for r in candidates],
        "invoice_id": invoice.id if invoice else None,
        "invoice_code": invoice.code if invoice else None,
    }


# passed rolls of an order that sit on no dispatch yet
def _free_rolls(db: Session, order_id: int, band: str | None = None) -> list[Roll]:
    stmt = (
        select(Roll)
        .outerjoin(DispatchRoll, DispatchRoll.roll_id == Roll.id)
        .where(
            Roll.order_id == order_id,
            Roll.status == RollStatus.passed,
            DispatchRoll.id.is_(None),
        )
        .order_by(Roll.code)
    )
    if band:
        stmt = stmt.where(Roll.shade_band == band)
    return list(db.scalars(stmt))


# finished goods shelf grouped by order: free rolls and rolls already on an open truck
def shelf(db: Session) -> list[dict]:
    now = _now()
    locs = _location_codes(db)
    rolls = list(
        db.scalars(
            select(Roll).where(Roll.status == RollStatus.passed).order_by(Roll.passed_at, Roll.id)
        )
    )
    on_dispatch = dict(
        db.execute(
            select(DispatchRoll.roll_id, Dispatch.code)
            .join(Dispatch, Dispatch.id == DispatchRoll.dispatch_id)
            .where(DispatchRoll.roll_id.in_([r.id for r in rolls] or [0]))
        ).all()
    )
    by_order: dict[int, list[Roll]] = defaultdict(list)
    for r in rolls:
        by_order[r.order_id].append(r)
    groups = []
    for order_id, order_rolls in by_order.items():
        order = db.get(Order, order_id)
        groups.append(
            {
                "order_id": order.id,
                "order_code": order.code,
                "buyer_name": db.get(Buyer, order.buyer_id).name,
                "order_open": order.status == OrderStatus.confirmed,
                "ordered_m": order.qty_m,
                "shipped_m": shipped_metres(db, order.id),
                "free_m": qty(
                    sum((r.length_m for r in order_rolls if r.id not in on_dispatch), ZERO)
                ),
                "on_truck_m": qty(
                    sum((r.length_m for r in order_rolls if r.id in on_dispatch), ZERO)
                ),
                "rolls": [
                    {
                        **_roll_row(r, locs),
                        "order_id": r.order_id,
                        "days_on_shelf": _days_on_shelf(r, now),
                        "dispatch_code": on_dispatch.get(r.id),
                    }
                    for r in order_rolls
                ],
            }
        )
    # open orders first, then oldest stock first
    return sorted(groups, key=lambda g: (not g["order_open"], g["order_code"]))


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# rolls on the shelf: passed QC, not on any dispatch; optional order / shade band filter
def finished_stock(
    db: Session, order_id: int | None = None, shade_band: str | None = None
) -> list[Roll]:
    stmt = (
        select(Roll)
        .outerjoin(DispatchRoll, DispatchRoll.roll_id == Roll.id)
        .where(Roll.status == RollStatus.passed, DispatchRoll.id.is_(None))
        .order_by(Roll.passed_at, Roll.id)
    )
    if order_id:
        stmt = stmt.where(Roll.order_id == order_id)
    if shade_band:
        stmt = stmt.where(Roll.shade_band == shade_band)
    return list(db.scalars(stmt))


# shipped (confirmed trucks) covers the order, give or take CLOSE_TOLERANCE
def order_fully_shipped(db: Session, order_id: int) -> bool:
    db.flush()  # confirm calls this before commit: its own truck must count
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    return shipped_metres(db, order_id) >= order.qty_m * (1 - CLOSE_TOLERANCE)


# trucks left open: started long ago and never sent, or their order is no longer open
def _stale_trucks(db: Session, now: datetime) -> list[dict]:
    rows = db.execute(
        select(Dispatch, Order, func.coalesce(func.sum(Roll.length_m), 0))
        .join(Order, Order.id == Dispatch.order_id)
        .outerjoin(DispatchRoll, DispatchRoll.dispatch_id == Dispatch.id)
        .outerjoin(Roll, Roll.id == DispatchRoll.roll_id)
        .where(Dispatch.status.in_(OPEN))
        .group_by(Dispatch.id, Order.id)
        .order_by(Dispatch.created_at, Dispatch.id)
    ).all()
    items = []
    for d, order, metres in rows:
        hours = int((now - d.created_at).total_seconds() // 3600)
        reasons = []
        if hours >= STALE_TRUCK_HOURS:
            reasons.append(f"truck open {hours} h, not sent")
        if order.status != OrderStatus.confirmed:
            reasons.append(f"order is {order.status}")
        if reasons:
            items.append(
                {
                    "kind": "dispatch",
                    "roll_id": None,
                    "roll_code": None,
                    "dispatch_id": d.id,
                    "dispatch_code": d.code,
                    "order_code": order.code,
                    "length_m": qty(metres),
                    "days_on_shelf": hours // 24,
                    "reasons": reasons,
                }
            )
    return items


# rolls forgotten in a corner: too long on shelf, order not open, or order already fully
# shipped; trucks left open come first
def corner_check(db: Session, days: int = SHELF_DAYS) -> list[dict]:
    now = _now()
    items = []
    orders: dict[int, tuple[Order, Decimal]] = {}
    for r in finished_stock(db):
        if r.order_id not in orders:
            order = db.get(Order, r.order_id)
            orders[r.order_id] = (order, shipped_metres(db, order.id))
        order, shipped = orders[r.order_id]
        reasons = []
        if _days_on_shelf(r, now) > days:
            reasons.append(f"on shelf over {days} days")
        if order.status != OrderStatus.confirmed:
            reasons.append(f"order is {order.status}")
        elif shipped >= order.qty_m:
            reasons.append("leftover: order already fully shipped")
        if reasons:
            items.append(
                {
                    "kind": "roll",
                    "roll_id": r.id,
                    "roll_code": r.code,
                    "dispatch_id": None,
                    "dispatch_code": None,
                    "order_code": order.code,
                    "length_m": r.length_m,
                    "days_on_shelf": _days_on_shelf(r, now),
                    "reasons": reasons,
                }
            )
    return _stale_trucks(db, now) + sorted(items, key=lambda i: -i["days_on_shelf"])


# --- writes: route-owned, each commits once and publishes after commit


# one open truck per order: a second "new dispatch" returns the one already open
def create_dispatch(
    db: Session, user: User, order_id: int, vehicle_no: str | None, driver: str | None
) -> Dispatch:
    order = _open_order(db, order_id, field="order_id")
    existing = db.scalar(
        select(Dispatch)
        .where(Dispatch.order_id == order.id, Dispatch.status.in_(OPEN))
        .order_by(Dispatch.id)
    )
    if existing:
        db.commit()  # nothing written; ends the transaction and frees the order lock
        return existing
    d = Dispatch(
        code=next_code(db, "DN"),
        order_id=order.id,
        buyer_id=order.buyer_id,
        vehicle_no=vehicle_no,
        driver=driver,
        status=DispatchStatus.draft,
    )
    db.add(d)
    db.flush()
    audit.record(db, user.id, "create", "dispatches", d.id, data={"order_id": order.id})
    db.commit()
    events.publish("dispatch", {"type": "created", "id": d.id})
    return d


def _editable(d: Dispatch) -> None:
    if d.status == DispatchStatus.confirmed:
        raise Conflict(
            f"Dispatch {d.code} is confirmed and cannot change", code="illegal_transition"
        )


def set_vehicle(
    db: Session, user: User, dispatch_id: int, vehicle_no: str, driver: str | None
) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _editable(d)
    d.vehicle_no, d.driver = vehicle_no, driver
    audit.record(db, user.id, "set_vehicle", "dispatches", d.id, data={"vehicle_no": vehicle_no})
    db.commit()
    events.publish("dispatch", {"type": "updated", "id": d.id})
    return get_detail(db, d.id)


def _scan_result(db: Session, d: Dispatch, roll_code: str) -> dict:
    loaded = _loaded(db, d.id)
    loaded_m = qty(sum((r.length_m for r in loaded), ZERO))
    order = db.get(Order, d.order_id)
    shipped, open_other = _order_metres(db, order.id, skip_dispatch=d.id)
    return {
        "dispatch_id": d.id,
        "status": d.status,
        "roll_code": roll_code,
        "roll_count": len(loaded),
        "loaded_m": loaded_m,
        "remaining_m": max(qty(order.qty_m - shipped - open_other - loaded_m), ZERO),
        "bands": sorted({r.shade_band for r in loaded if r.shade_band}),
    }


# one roll onto the truck. Locks dispatch then roll, so two scanners cannot load one roll twice.
def _load_roll(db: Session, user: User, dispatch_id: int, roll_code: str) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _editable(d)
    _open_order(db, d.order_id)
    roll = db.scalar(select(Roll).where(Roll.code == roll_code).with_for_update())
    if not roll:
        raise NotFound(f"No roll with code {roll_code}", field="roll_code")
    on = db.scalar(
        select(Dispatch)
        .join(DispatchRoll, DispatchRoll.dispatch_id == Dispatch.id)
        .where(DispatchRoll.roll_id == roll.id)
    )
    if on and on.id == d.id:
        return _scan_result(db, d, roll.code)  # same roll scanned twice onto same truck: no-op
    if roll.order_id != d.order_id:
        order = db.get(Order, roll.order_id)
        raise Conflict(
            f"{roll.code} belongs to order {order.code}, not this one",
            field="roll_code",
            code="wrong_order",
        )
    if roll.status == RollStatus.dispatched or on:
        where = on.code if on else "an earlier dispatch"
        raise Conflict(
            f"{roll.code} is already on {where}", field="roll_code", code="already_dispatched"
        )
    if roll.status != RollStatus.passed:
        raise Conflict(
            f"{roll.code} has not passed QC (status: {roll.status})",
            field="roll_code",
            code="not_passed",
        )
    before = _scan_result(db, d, roll.code)
    if before["remaining_m"] <= 0:
        raise Conflict(
            "Loaded rolls already cover the ordered metres", field="roll_code", code="order_covered"
        )
    if before["bands"] and roll.shade_band not in before["bands"] and not _has_override(db, d.id):
        raise Conflict(
            f"{roll.code} is shade {roll.shade_band}, truck has {', '.join(before['bands'])}. "
            "Mixing shades needs a supervisor override.",
            field="roll_code",
            code="shade_mismatch",
        )
    db.add(DispatchRoll(dispatch_id=d.id, roll_id=roll.id))
    if d.status == DispatchStatus.draft:
        check_transition(DISPATCH_TRANSITIONS, d.status, DispatchStatus.loading)
        d.status = DispatchStatus.loading
    db.flush()
    audit.record(db, user.id, "load_roll", "dispatches", d.id, data={"roll": roll.code})
    return _scan_result(db, d, roll.code)


def scan(db: Session, user: User, dispatch_id: int, roll_code: str, key: str | None) -> dict:
    result = run_once(
        db, key, "dispatch_scan", lambda: _load_roll(db, user, dispatch_id, roll_code)
    )
    db.commit()
    events.publish("dispatch", {"type": "loaded", "id": dispatch_id})
    return result


# roll off the truck; an empty truck goes back to draft. Caller commits.
def _take_off(db: Session, d: Dispatch, link: DispatchRoll) -> None:
    db.delete(link)
    db.flush()
    if d.status == DispatchStatus.loading and not _loaded(db, d.id):
        check_transition(DISPATCH_TRANSITIONS, d.status, DispatchStatus.draft)
        d.status = DispatchStatus.draft


def unload(db: Session, user: User, dispatch_id: int, roll_id: int) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _editable(d)
    link = db.scalar(
        select(DispatchRoll).where(
            DispatchRoll.dispatch_id == d.id, DispatchRoll.roll_id == roll_id
        )
    )
    if not link:
        raise NotFound("That roll is not on this dispatch", field="roll_id")
    _take_off(db, d, link)
    audit.record(db, user.id, "unload_roll", "dispatches", d.id, data={"roll_id": roll_id})
    db.commit()
    events.publish("dispatch", {"type": "unloaded", "id": d.id})
    return get_detail(db, d.id)


# truck not going: every roll back on the shelf, the draft is gone; the audit row keeps it
def cancel_dispatch(db: Session, user: User, dispatch_id: int) -> None:
    d = _get(db, dispatch_id, lock=True)
    _editable(d)
    rolls = [r.code for r in _loaded(db, d.id)]
    for link in db.scalars(select(DispatchRoll).where(DispatchRoll.dispatch_id == d.id)).all():
        _take_off(db, d, link)
    data = {"code": d.code, "order_id": d.order_id, "rolls": rolls}
    audit.record(db, user.id, "cancel", "dispatches", d.id, data=data)
    db.delete(d)
    db.commit()
    events.publish("dispatch", {"type": "cancelled", "id": dispatch_id})


# supervisor allows mixed shade bands on this one dispatch; the audit row is the record
def shade_override(db: Session, user: User, dispatch_id: int, reason: str) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _editable(d)
    audit.record(db, user.id, "shade_override", "dispatches", d.id, reason=reason)
    db.commit()
    events.publish("dispatch", {"type": "override", "id": d.id})
    return get_detail(db, d.id)


# metres of this roll sitting at this location, from the ledger
def _roll_on_hand(db: Session, roll_id: int, location_id: int) -> Decimal:
    moved_in = db.scalar(
        select(func.coalesce(func.sum(StockMove.qty), 0)).where(
            StockMove.roll_id == roll_id, StockMove.to_location_id == location_id
        )
    )
    moved_out = db.scalar(
        select(func.coalesce(func.sum(StockMove.qty), 0)).where(
            StockMove.roll_id == roll_id, StockMove.from_location_id == location_id
        )
    )
    return Decimal(moved_in) - Decimal(moved_out)


# one transaction: rolls dispatched, stock moved out, invoice from exactly the loaded rolls
def confirm(db: Session, user: User, dispatch_id: int) -> dict:
    d = _get(db, dispatch_id, lock=True)
    check_transition(DISPATCH_TRANSITIONS, d.status, DispatchStatus.confirmed)
    _open_order(db, d.order_id)
    if not d.vehicle_no:
        raise Unprocessable("Vehicle number is needed before the truck leaves", field="vehicle_no")
    rolls = _loaded(db, d.id, lock=True)
    if not rolls:
        raise Conflict("No rolls loaded", field="rolls")
    if len({r.shade_band for r in rolls}) > 1 and not _has_override(db, d.id):
        raise Conflict("Mixed shade bands need a supervisor override", code="shade_mismatch")
    dispatched_loc = _location_id(db, LocationKind.dispatched)
    now = _now()
    for r in rolls:
        if r.order_id != d.order_id:
            raise Conflict(f"{r.code} belongs to another order", code="wrong_order")
        check_transition(ROLL_TRANSITIONS, r.status, RollStatus.dispatched)
        if _roll_on_hand(db, r.id, r.location_id) < r.length_m:
            raise Conflict(
                f"Stock ledger does not show {r.code} at its location", code="stock_mismatch"
            )
        db.add(
            StockMove(
                at=now,
                item_kind=ItemKind.fabric,
                roll_id=r.id,
                qty=r.length_m,
                unit=Unit.m,
                from_location_id=r.location_id,
                to_location_id=dispatched_loc,
                reason=MoveReason.dispatch,
                ref_type="dispatch",
                ref_id=d.id,
                user_id=user.id,
            )
        )
        r.status, r.location_id = RollStatus.dispatched, dispatched_loc
    check_transition(DISPATCH_TRANSITIONS, d.status, DispatchStatus.confirmed)
    d.status, d.confirmed_at = DispatchStatus.confirmed, now
    invoice = finance.issue_invoice(db, user.id, d, rolls)
    audit.record(
        db,
        user.id,
        "confirm",
        "dispatches",
        d.id,
        data={"rolls": [r.code for r in rolls], "invoice": invoice.code},
    )
    closed, reserved = _close_if_shipped(db, d.order_id, user.id)
    db.commit()
    for topic in ("dispatch", "stock", "orders"):
        events.publish(topic, {"type": "dispatched", "id": d.id})
    if closed:
        events.publish("orders", {"type": "closed", "id": d.order_id})
        inventory.publish_orders(r.order_id for r in reserved)
    return get_detail(db, d.id)


# the last truck closes the order and hands its leftover yarn on; a job still on a machine or
# another open truck keeps it open (accounts closes it later)
def _close_if_shipped(db: Session, order_id: int, user_id: int) -> tuple[bool, list]:
    if not order_fully_shipped(db, order_id):
        return False, []
    try:
        orders.close_order(db, order_id, user_id)
    except Conflict:
        return False, []
    return True, inventory.reserve_short_orders(db, user_id)
