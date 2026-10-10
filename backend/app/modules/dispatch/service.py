import hmac
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit, events, mail
from app.core.codes import next_code
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import Unit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.idempotency import run_once
from app.core.pagination import Page
from app.core.states import check_transition
from app.core.units import fully_shipped, qty
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.finance import service as finance
from app.modules.finance.models import Invoice
from app.modules.inventory import service as inventory
from app.modules.inventory.models import ItemKind, MoveReason, StockMove
from app.modules.masters.models import Buyer, FabricType, Location, LocationKind
from app.modules.orders import service as orders
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrder, WorkOrderStatus
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
OPEN = (DispatchStatus.draft, DispatchStatus.loading)
# wrong delivery codes before the code locks; 6 digits and 5 tries leave a 1 in 200,000 guess
OTP_TRIES = 5
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
            "driver_email": d.driver_email,
            "delivered_at": d.delivered_at,
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
        **{c: getattr(d, c) for c in ("delivered_at", "received_by", "delivery_note")},
        "driver_email": d.driver_email,
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
        "delivery_token": d.delivery_token if d.status == DispatchStatus.confirmed else None,
        "has_code": d.delivery_otp is not None,
        "tries_left": _tries_left(d),
        "mail_on": mail.enabled(),
        "driver_mail": mail.last_attempt(db, "driver", ("dispatches", d.id)),
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


# orders the floor or QC still owe rolls to: a job not done, or a roll not yet decided
def _jobs_open():
    return select(WorkOrder.order_id).where(WorkOrder.status != WorkOrderStatus.done)


def _rolls_open():
    return select(Roll.order_id).where(
        Roll.status.in_([RollStatus.in_process, RollStatus.awaiting_qc, RollStatus.rework])
    )


def _still_making(db: Session, order_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.id == order_id,
                or_(Order.id.in_(_jobs_open()), Order.id.in_(_rolls_open())),
            )
        )
    )


# draft the order's next truck: one shade band that covers the rest, or, once nothing more is
# coming, the band that gets closest (the rest goes on the next truck, still one band each).
# Runs on a QC decision and after a truck is confirmed. Order row lock: never two open trucks
def auto_draft(
    db: Session, order_id: int, user_id: int, at: datetime | None = None
) -> Dispatch | None:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != OrderStatus.confirmed:
        return None
    open_truck = select(Dispatch.id).where(
        Dispatch.order_id == order.id, Dispatch.status != DispatchStatus.confirmed
    )
    if db.scalar(open_truck):
        return None
    shipped, _ = _order_metres(db, order.id)
    pick = pick_rolls(_free_rolls(db, order.id), qty(order.qty_m - shipped))
    if not pick or (pick.short > 0 and _still_making(db, order.id)):
        return None
    d = Dispatch(
        code=next_code(db, "DN"),
        order_id=order.id,
        buyer_id=order.buyer_id,
        status=DispatchStatus.draft,
    )
    if at:
        d.created_at = at
    db.add(d)
    db.flush()
    data = {"order_id": order.id, "band": pick.band, "roll_ids": [r.id for r in pick.rolls]}
    audit.record(db, user_id, "auto_draft", "dispatches", d.id, data=data)
    return d


# what waits on the dispatch desk and the floor: open trucks with rolls to load or ready to
# send, trucks whose rest needs another shade band (a supervisor's call), and passed rolls of
# an open order with no truck at all (no single band covered it, so none was drafted)
def open_truck_work(db: Session) -> list[dict]:
    out = []
    trucks = db.execute(
        select(Dispatch, Order)
        .join(Order, Order.id == Dispatch.order_id)
        .where(Dispatch.status != DispatchStatus.confirmed, Order.status == OrderStatus.confirmed)
        .order_by(Dispatch.id)
    ).all()
    with_truck = {o.id for _, o in trucks}
    for d, order in trucks:
        loaded = _loaded(db, d.id)
        free = _free_rolls(db, order.id)
        shipped, on_trucks = _order_metres(db, order.id)
        need = order.qty_m - shipped - on_trucks
        bands = {r.shade_band for r in loaded}
        same = [r for r in free if r.shade_band in bands]
        if not loaded:  # empty truck: what its proposal would load, one band
            pick = pick_rolls(free, qty(need))
            same = pick.rolls if pick else []
        if loaded and need <= 0:
            kind = "confirm"
        elif same:
            kind = "load"
        elif free and bands and not _has_override(db, d.id):
            kind = "shade"
        else:
            continue
        out.append(
            {
                "kind": kind,
                "dispatch_id": d.id,
                "code": d.code,
                "order_id": order.id,
                "order_code": order.code,
                "rolls": len(same) if kind == "load" else len(free),
                "since": d.created_at,
            }
        )
    # nothing left to make or check: the floor and QC are finished with the order
    for order in db.scalars(
        select(Order)
        .where(
            Order.status == OrderStatus.confirmed,
            Order.id.not_in(with_truck or {0}),
            Order.id.not_in(_jobs_open()),
            Order.id.not_in(_rolls_open()),
        )
        .order_by(Order.deadline, Order.id)
    ):
        free = _free_rolls(db, order.id)
        if free:
            out.append(
                {
                    "kind": "no_truck",
                    "dispatch_id": None,
                    "code": None,
                    "order_id": order.id,
                    "order_code": order.code,
                    "rolls": len(free),
                    "since": min(r.passed_at or r.created_at for r in free),
                }
            )
    return out


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


# shipped (confirmed trucks) covers the order, by the one fully-shipped rule
def order_fully_shipped(db: Session, order_id: int) -> bool:
    db.flush()  # confirm calls this before commit: its own truck must count
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    return fully_shipped(shipped_metres(db, order_id), order.qty_m)


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
        elif fully_shipped(shipped, order.qty_m):
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
    db: Session,
    user: User,
    order_id: int,
    vehicle_no: str | None,
    driver: str | None,
    driver_email: str | None = None,
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
        driver_email=driver_email,
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
    db: Session,
    user: User,
    dispatch_id: int,
    vehicle_no: str,
    driver: str | None,
    driver_email: str | None = None,
) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _editable(d)
    d.vehicle_no, d.driver, d.driver_email = vehicle_no, driver, driver_email
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
    # order row lock: a cancel and this truck cannot pass each other
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
    open_delivery(d)
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
    following = None if closed else auto_draft(db, d.order_id, user.id)  # the rest, next truck
    db.commit()
    for topic in ("dispatch", "stock", "orders"):
        events.publish(topic, {"type": "dispatched", "id": d.id})
    if closed:
        events.publish("orders", {"type": "closed", "id": d.order_id})
        inventory.publish_orders(r.order_id for r in reserved)
    if following:
        events.publish("dispatch", {"type": "auto_draft", "code": following.code})
    return get_detail(db, d.id)


# the last truck closes the order and hands its leftover yarn on; a job still on a machine or
# another open truck keeps it open (accounts closes it later)
def _close_if_shipped(db: Session, order_id: int, user_id: int) -> tuple[bool, list]:
    if not order_fully_shipped(db, order_id):
        return False, []
    # an empty draft (one drafted for a rest that this truck already took) holds nothing back
    for d in db.scalars(
        select(Dispatch).where(
            Dispatch.order_id == order_id,
            Dispatch.status == DispatchStatus.draft,
            Dispatch.id.not_in(select(DispatchRoll.dispatch_id)),
        )
    ).all():
        audit.record(
            db, user_id, "cancel", "dispatches", d.id, "order fully shipped", {"code": d.code}
        )
        db.delete(d)
    db.flush()
    try:
        orders.close_order(db, order_id, user_id)
    except Conflict:
        return False, []
    return True, inventory.reserve_short_orders(db, user_id)


# --- delivery: the driver link plus the buyer's code close the trip


def _tries_left(d: Dispatch) -> int:
    return max(OTP_TRIES - d.otp_tries, 0)


# a truck that leaves gets a fresh code; only the buyer link ever shows it
def open_delivery(d: Dispatch) -> None:
    d.delivery_otp, d.otp_tries = f"{secrets.randbelow(10**6):06d}", 0


def _by_token(db: Session, token: str, lock: bool = False) -> Dispatch:
    stmt = select(Dispatch).where(Dispatch.delivery_token == token)
    d = db.scalar(stmt.with_for_update() if lock else stmt)
    # a truck still at the mill has no trip to close: same answer as a wrong link
    if not d or d.status != DispatchStatus.confirmed:
        raise NotFound("Delivery link is not valid")
    return d


def _has_left(d: Dispatch) -> None:
    if d.status != DispatchStatus.confirmed:
        raise Conflict(f"{d.code} has not left the mill yet", code="not_left")


def _delivery_view(db: Session, d: Dispatch) -> dict:
    order = db.get(Order, d.order_id)
    buyer = db.get(Buyer, d.buyer_id)
    rolls = _loaded(db, d.id)
    return {
        "challan": d.code,
        "order_code": order.code,
        "buyer_name": buyer.name,
        "buyer_city": buyer.city,
        "fabric": db.get(FabricType, order.fabric_type_id).name,
        "colour": order.colour,
        "vehicle_no": d.vehicle_no,
        "driver": d.driver,
        "left_at": d.confirmed_at,
        "rolls": [{"code": r.code, "length_m": r.length_m} for r in rolls],
        "roll_count": len(rolls),
        "metres": qty(sum((r.length_m for r in rolls), ZERO)),
        "delivered_at": d.delivered_at,
        "received_by": d.received_by,
        "delivery_note": d.delivery_note,
        "tries_left": _tries_left(d),
        "has_code": d.delivery_otp is not None,
    }


def delivery_view(db: Session, token: str) -> dict:
    return _delivery_view(db, _by_token(db, token))


# one check for the driver link and the office phone path; caller holds the dispatch row lock,
# so two guesses at once cannot both use the last try
def _close_trip(db: Session, d: Dispatch, user_id: int | None, data: dict, via: str) -> None:
    if d.delivered_at:
        return  # repeat submit after a flaky network: already done, change nothing
    if not d.delivery_otp:
        raise Conflict("No delivery code yet. Ask the mill office for one.", code="no_code")
    if d.otp_tries >= OTP_TRIES:
        raise Conflict(
            "Too many wrong codes. Ask the mill office for a new code.",
            field="otp",
            code="otp_locked",
        )
    if not hmac.compare_digest(data["otp"], d.delivery_otp):
        d.otp_tries += 1
        tries = {"via": via, "tries": d.otp_tries}
        audit.record(db, user_id, "delivery_code_wrong", "dispatches", d.id, data=tries)
        db.commit()
        events.publish("dispatch", {"type": "code_wrong", "id": d.id})
        left = _tries_left(d)
        msg = {0: "The code is now locked: ask the mill office for a new one.", 1: "1 try left."}
        raise Unprocessable(
            f"Wrong code. {msg.get(left, f'{left} tries left.')}", field="otp", code="wrong_otp"
        )
    d.delivered_at = _now()
    d.received_by, d.delivery_note = data["received_by"], data.get("note")
    proof = {"via": via, "received_by": d.received_by, "note": d.delivery_note}
    audit.record(db, user_id, "delivered", "dispatches", d.id, data=proof)
    db.commit()
    for topic in ("dispatch", "orders"):
        events.publish(topic, {"type": "delivered", "id": d.id})


# public: driver link, no login; the buyer's code is the signature
def deliver(db: Session, token: str, data: dict) -> dict:
    d = _by_token(db, token, lock=True)
    _close_trip(db, d, None, data, "driver_link")
    return _delivery_view(db, d)


# driver has no signal at the gate: reads the code out on the phone, the clerk types it
def office_deliver(db: Session, user: User, dispatch_id: int, data: dict) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _has_left(d)
    _close_trip(db, d, user.id, data, "office_phone")
    return get_detail(db, d.id)


# locked or lost code: a fresh one shows on the buyer link, tries start again
def new_code(db: Session, user: User, dispatch_id: int) -> dict:
    d = _get(db, dispatch_id, lock=True)
    _has_left(d)
    if d.delivered_at:
        raise Conflict(f"{d.code} is already delivered", code="delivered")
    open_delivery(d)
    audit.record(db, user.id, "delivery_code_reissued", "dispatches", d.id)
    db.commit()
    events.publish("dispatch", {"type": "code_reissued", "id": d.id})
    return get_detail(db, d.id)


# --- driver link email


def _driver_letter(db: Session, d: Dispatch) -> mail.Letter:
    buyer = db.get(Buyer, d.buyer_id)
    rolls = _loaded(db, d.id)
    loaded_m = qty(sum((r.length_m for r in rolls), ZERO))
    place = f"{buyer.name}, {buyer.city}" if buyer.city else buyer.name
    url = f"{get_settings().web_url.rstrip('/')}/deliver/{d.delivery_token}"
    body = (
        f"Hello {d.driver or 'driver'},\n\n"
        f"Delivery {d.code} on {d.vehicle_no}: {len(rolls)} rolls, "
        f"{loaded_m.normalize():,f} m to {place}.\n\n"
        "At the buyer's gate, open this page and count the rolls with the buyer:\n"
        f"{url}\n\n"
        "When the count is right, ask the buyer for the delivery code on their order page and "
        "enter it with the name of the person who received the rolls.\n\n"
        "Everest Textile Mills"
    )
    subject = f"Delivery {d.code} to {buyer.name}"
    return mail.Letter(d.driver_email, subject, body, "No driver email on this truck")


# shared service: email the driver their link (never the code); result is an audit row.
# Caller commits.
def email_driver(db: Session, dispatch_id: int, user_id: int | None) -> str:
    d = _get(db, dispatch_id)
    return mail.attempt(db, user_id, "driver", ("dispatches", d.id), _driver_letter(db, d))


# after confirm, off the request on its own session: the truck leaves without waiting for mail
def email_driver_later(dispatch_id: int, user_id: int) -> None:
    if not mail.enabled():
        return
    with SessionLocal() as db:
        email_driver(db, dispatch_id, user_id)
        db.commit()
    events.publish("dispatch", {"type": "driver_email", "id": dispatch_id})


# resend, or a first send once the clerk fills in a missing or wrong address
def resend_driver(db: Session, user: User, dispatch_id: int, driver_email: str | None) -> dict:
    mail.require_on()
    d = _get(db, dispatch_id, lock=True)
    _has_left(d)
    if d.delivered_at:
        raise Conflict(f"{d.code} is already delivered", code="delivered")
    if driver_email and driver_email != d.driver_email:
        d.driver_email = driver_email
        data = {"driver_email": driver_email}
        audit.record(db, user.id, "set_driver_email", "dispatches", d.id, data=data)
    email_driver(db, d.id, user.id)
    db.commit()
    events.publish("dispatch", {"type": "driver_email", "id": d.id})
    return get_detail(db, d.id)
