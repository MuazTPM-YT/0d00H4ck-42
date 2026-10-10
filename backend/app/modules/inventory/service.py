from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.core import audit, events
from app.core.audit import AuditLog
from app.core.enums import Source, Stage, Unit
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.core.units import qty
from app.modules.auth.models import User
from app.modules.inventory.models import (
    BatchStatus,
    ExpectedDelivery,
    ExpectedDeliveryStatus,
    ItemKind,
    MoveReason,
    Receipt,
    ReceiptStatus,
    Reservation,
    ReservationStatus,
    StockMove,
    YarnBatch,
)
from app.modules.masters.models import Location, LocationKind, YarnItem
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrder, WorkOrderStatus

BATCH_TRANSITIONS = {
    BatchStatus.pending_identification: {
        BatchStatus.inspection,
        BatchStatus.quarantined,
        BatchStatus.rejected,
    },
    BatchStatus.inspection: {BatchStatus.approved, BatchStatus.quarantined, BatchStatus.rejected},
    BatchStatus.quarantined: {BatchStatus.approved, BatchStatus.rejected},
    BatchStatus.approved: {BatchStatus.quarantined},
}
RECEIPT_TRANSITIONS = {ReceiptStatus.draft: {ReceiptStatus.confirmed}}
EXPECTED_DELIVERY_TRANSITIONS = {
    ExpectedDeliveryStatus.open: {
        ExpectedDeliveryStatus.partially_received,
        ExpectedDeliveryStatus.received,
        ExpectedDeliveryStatus.cancelled,
    },
    ExpectedDeliveryStatus.partially_received: {
        ExpectedDeliveryStatus.received,
        ExpectedDeliveryStatus.cancelled,
    },
}
RESERVATION_TRANSITIONS = {
    ReservationStatus.active: {ReservationStatus.consumed, ReservationStatus.released},
}
ZERO = Decimal("0.000")
# yarn kinds that hold real stock inside the mill (supplier is a virtual source)
HOLDING = (LocationKind.inspection, LocationKind.quarantine, LocationKind.store)


def item_label(item: YarnItem | None) -> str | None:
    return f"{item.fibre} {item.count} {item.colour}" if item else None


# case-insensitive: "navy" on a label is the same yarn as "Navy" in masters
def find_item(db: Session, fibre: str, count: str, colour: str) -> YarnItem | None:
    return db.scalar(
        select(YarnItem).where(
            func.lower(YarnItem.fibre) == fibre.strip().lower(),
            func.lower(YarnItem.count) == count.strip().lower(),
            func.lower(YarnItem.colour) == colour.strip().lower(),
        )
    )


# ---------------------------------------------------------------- ledger reads


def location_id(db: Session, kind: LocationKind) -> int:
    loc = db.scalar(select(Location.id).where(Location.kind == kind).order_by(Location.id))
    if loc is None:
        raise Conflict(f"No '{kind}' location is set up. Run the seed or add one.")
    return loc


# every move is +qty at its destination and -qty at its source; sum per batch per location kind.
# Filtering by batch uses ix_stock_moves_batch_to / ix_stock_moves_batch_from.
def balances(db: Session, batch_ids=None) -> dict[int, dict[LocationKind, Decimal]]:
    legs_in = select(
        StockMove.yarn_batch_id.label("batch_id"),
        StockMove.to_location_id.label("loc_id"),
        StockMove.qty.label("qty"),
    ).where(StockMove.item_kind == ItemKind.yarn)
    legs_out = select(StockMove.yarn_batch_id, StockMove.from_location_id, -StockMove.qty).where(
        StockMove.item_kind == ItemKind.yarn
    )
    if batch_ids is not None:
        legs_in = legs_in.where(StockMove.yarn_batch_id.in_(batch_ids))
        legs_out = legs_out.where(StockMove.yarn_batch_id.in_(batch_ids))
    legs = union_all(legs_in, legs_out).subquery()
    rows = db.execute(
        select(legs.c.batch_id, Location.kind, func.sum(legs.c.qty))
        .join(Location, Location.id == legs.c.loc_id)
        .group_by(legs.c.batch_id, Location.kind)
    ).all()
    out: dict[int, dict[LocationKind, Decimal]] = defaultdict(dict)
    for batch_id, kind, kg in rows:
        if kg:
            out[batch_id][kind] = qty(kg)
    return out


def batch_kg_at(db: Session, batch_id: int, kind: LocationKind) -> Decimal:
    return balances(db, [batch_id]).get(batch_id, {}).get(kind, ZERO)


# active reserved kg per batch; optionally only one order's
def reserved_by_batch(db: Session, batch_ids, order_id: int | None = None) -> dict[int, Decimal]:
    stmt = (
        select(Reservation.yarn_batch_id, func.sum(Reservation.kg))
        .where(
            Reservation.status == ReservationStatus.active,
            Reservation.yarn_batch_id.in_(batch_ids),
        )
        .group_by(Reservation.yarn_batch_id)
    )
    if order_id is not None:
        stmt = stmt.where(Reservation.order_id == order_id)
    return {b: qty(kg) for b, kg in db.execute(stmt).all()}


# net kg issued to an order's work orders (issues minus returns), per yarn item
def issued_by_item(db: Session, order_id: int) -> dict[int, Decimal]:
    rows = db.execute(
        select(YarnBatch.yarn_item_id, StockMove.reason, func.sum(StockMove.qty))
        .join(YarnBatch, YarnBatch.id == StockMove.yarn_batch_id)
        .join(WorkOrder, WorkOrder.id == StockMove.ref_id)
        .where(
            StockMove.ref_type == "work_order",
            StockMove.reason.in_([MoveReason.issue, MoveReason.return_]),
            WorkOrder.order_id == order_id,
        )
        .group_by(YarnBatch.yarn_item_id, StockMove.reason)
    ).all()
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for item_id, reason, kg in rows:
        out[item_id] += kg if reason == MoveReason.issue else -kg
    return {k: qty(v) for k, v in out.items()}


# net kg of one batch issued to one work order (issues minus returns)
def issued_to_work_order(db: Session, work_order_id: int, batch_id: int) -> Decimal:
    return _work_order_net(db, work_order_id, batch_id, (MoveReason.return_,))


# kg of one batch still on the floor for one work order (issued - returned - consumed)
def held_by_work_order(db: Session, work_order_id: int, batch_id: int) -> Decimal:
    return _work_order_net(db, work_order_id, batch_id, (MoveReason.return_, MoveReason.consume))


def _work_order_net(db: Session, work_order_id: int, batch_id: int, minus) -> Decimal:
    rows = db.execute(
        select(StockMove.reason, func.sum(StockMove.qty))
        .where(
            StockMove.ref_type == "work_order",
            StockMove.ref_id == work_order_id,
            StockMove.yarn_batch_id == batch_id,
            StockMove.reason.in_([MoveReason.issue, *minus]),
        )
        .group_by(StockMove.reason)
    ).all()
    return qty(sum((kg if r == MoveReason.issue else -kg for r, kg in rows), ZERO))


# kg received so far against one expected delivery (confirmed receipts only)
def delivery_received_kg(db: Session, delivery_id: int) -> Decimal:
    kg = db.scalar(
        select(func.coalesce(func.sum(YarnBatch.received_kg), 0))
        .join(Receipt, Receipt.id == YarnBatch.receipt_id)
        .where(
            Receipt.expected_delivery_id == delivery_id,
            Receipt.status == ReceiptStatus.confirmed,
        )
    )
    return qty(kg)


# what an order needs per yarn component, with the matching yarn item (None if not in masters)
def order_needs(db: Session, order: Order) -> list[dict]:
    # orders.service imports this module; importing here breaks the cycle
    from app.modules.orders.service import yarn_components

    out = []
    for c in yarn_components(order.qty_m, order.fabric_type, order.colour):
        item = find_item(db, c["fibre"], c["count"], c["colour"])
        out.append({**c, "yarn_item_id": item.id if item else None})
    return out


# ---------------------------------------------------------------- ledger writes


# the one place a yarn move is written; refuses to take a location below zero
def move_yarn(
    db: Session,
    batch: YarnBatch,
    kg: Decimal,
    frm: LocationKind,
    to: LocationKind,
    reason: MoveReason,
    user_id: int | None,
    ref: tuple[str, int] | None = None,
    source: Source = Source.manual,
    idempotency_key: str | None = None,
) -> StockMove:
    kg = qty(kg)
    if kg <= 0:
        raise BadRequest("Quantity must be greater than 0", field="kg")
    if frm != LocationKind.supplier:
        have = batch_kg_at(db, batch.id, frm)
        if kg > have:
            raise Conflict(
                f"Only {have} kg of {batch.code} is in {frm}; cannot move {kg} kg",
                field="kg",
                code="insufficient_stock",
            )
    ref_type, ref_id = ref or ("yarn_batch", batch.id)
    move = StockMove(
        item_kind=ItemKind.yarn,
        yarn_batch_id=batch.id,
        qty=kg,
        unit=Unit.kg,
        from_location_id=location_id(db, frm),
        to_location_id=location_id(db, to),
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        user_id=user_id,
        source=source,
        idempotency_key=idempotency_key,
    )
    db.add(move)
    db.flush()
    return move


# row lock on the batch so two writers queue up instead of racing
def _lock_batch(db: Session, batch_id: int) -> YarnBatch:
    locked = db.scalar(select(YarnBatch.id).where(YarnBatch.id == batch_id).with_for_update())
    if locked is None:
        raise NotFound(f"Yarn batch {batch_id} not found")
    return db.get(YarnBatch, batch_id, populate_existing=True)


def _set_status(db: Session, batch: YarnBatch, new: BatchStatus) -> None:
    check_transition(BATCH_TRANSITIONS, batch.status, new)
    batch.status = new


def _release_reservations(db: Session, where, user_id: int | None, reason: str) -> int:
    rows = db.scalars(
        select(Reservation).where(Reservation.status == ReservationStatus.active, where)
    ).all()
    for r in rows:
        check_transition(RESERVATION_TRANSITIONS, r.status, ReservationStatus.released)
        r.status = ReservationStatus.released
        audit.record(db, user_id, "release", "reservations", r.id, reason=reason)
    return len(rows)


# ---------------------------------------------------------------- shared services
# contract: docs/contracts.md. Never commit; caller owns the transaction.


# approved kg sitting in store locations for this yarn item (ledger sum, approved batches only)
def stock_on_hand(db: Session, yarn_item_id: int) -> Decimal:
    ids = _approved_batch_ids(db, yarn_item_id)
    bal = balances(db, ids)
    return qty(sum((bal.get(b, {}).get(LocationKind.store, ZERO) for b in ids), ZERO))


# stock_on_hand minus active reservations
def free_stock(db: Session, yarn_item_id: int) -> Decimal:
    ids = _approved_batch_ids(db, yarn_item_id)
    return qty(stock_on_hand(db, yarn_item_id) - sum(reserved_by_batch(db, ids).values(), ZERO))


def _approved_batch_ids(db: Session, yarn_item_id: int) -> list[int]:
    return list(
        db.scalars(
            select(YarnBatch.id).where(
                YarnBatch.yarn_item_id == yarn_item_id, YarnBatch.status == BatchStatus.approved
            )
        )
    )


# lot choice for one need. lots = [(batch_id, free_kg)].
# 1) best fit: the smallest single lot that covers the need (no lot mixing, keeps big lots whole)
# 2) else greedy largest first: taking the k largest gives the biggest sum for any k, so this
#    uses the fewest lots possible. Ties go to the older batch (lower id) = FIFO.
def pick_lots(need: Decimal, lots: list[tuple[int, Decimal]]) -> list[tuple[int, Decimal]]:
    lots = [(b, free) for b, free in lots if free > 0]
    covering = [(b, free) for b, free in lots if free >= need]
    if covering:
        best, _ = min(covering, key=lambda lot: (lot[1], lot[0]))
        return [(best, qty(need))]
    picks = []
    for b, free in sorted(lots, key=lambda lot: (-lot[1], lot[0])):
        if need <= 0:
            break
        take = min(free, need)
        picks.append((b, qty(take)))
        need -= take
    return picks


# reserve what a confirmed order still lacks. Locks the order row and every approved batch of
# the item (FOR UPDATE), so two orders reserving at once queue and never share the same kilos.
# Yarn tagged to this order at receipt is used first.
def reserve(db: Session, order_id: int, user_id: int | None) -> list[Reservation]:
    locked = db.scalar(select(Order.id).where(Order.id == order_id).with_for_update())
    if locked is None:
        raise NotFound(f"Order {order_id} not found")
    order = db.get(Order, order_id, populate_existing=True)
    if order.status != OrderStatus.confirmed:
        raise Conflict("Only confirmed orders reserve yarn", field="status")

    issued = issued_by_item(db, order.id)
    created: list[Reservation] = []
    for need in order_needs(db, order):
        item_id = need["yarn_item_id"]
        if item_id is None:
            continue
        batch_ids = list(
            db.scalars(
                select(YarnBatch.id)
                .where(YarnBatch.yarn_item_id == item_id, YarnBatch.status == BatchStatus.approved)
                .order_by(YarnBatch.id)
                .with_for_update()
            )
        )
        if not batch_ids:
            continue
        mine = sum(reserved_by_batch(db, batch_ids, order_id=order.id).values(), ZERO)
        remaining = need["kg_needed"] - mine - issued.get(item_id, ZERO)
        if remaining <= 0:
            continue

        store = balances(db, batch_ids)
        taken = reserved_by_batch(db, batch_ids)
        tagged = set(
            db.scalars(
                select(YarnBatch.id).where(
                    YarnBatch.id.in_(batch_ids), YarnBatch.order_id == order.id
                )
            )
        )
        lots = [
            (b, store.get(b, {}).get(LocationKind.store, ZERO) - taken.get(b, ZERO))
            for b in batch_ids
        ]
        picks = pick_lots(remaining, [lot for lot in lots if lot[0] in tagged])
        left = remaining - sum((kg for _, kg in picks), ZERO)
        if left > 0:
            picks += pick_lots(left, [lot for lot in lots if lot[0] not in tagged])

        new = [Reservation(yarn_batch_id=b, order_id=order.id, kg=kg) for b, kg in picks]
        db.add_all(new)
        db.flush()
        for r in new:
            audit.record(
                db,
                user_id,
                "reserve",
                "reservations",
                r.id,
                data={"kg": str(r.kg), "order": order.id},
            )
        created += new
        lots_used = db.scalar(
            select(func.count(func.distinct(Reservation.yarn_batch_id))).where(
                Reservation.order_id == order.id,
                Reservation.yarn_batch_id.in_(batch_ids),
                Reservation.status.in_([ReservationStatus.active, ReservationStatus.consumed]),
            )
        )
        if new and lots_used > 1:
            audit.record(
                db,
                user_id,
                "mixed_lots",
                "orders",
                order.id,
                reason=f"{need['count']} {need['colour']} on {lots_used} lots (barre risk)",
            )
    return created


# order cancelled: give its reserved kilos back to free stock
def release_order(db: Session, order_id: int, user_id: int | None, reason: str) -> int:
    return _release_reservations(db, Reservation.order_id == order_id, user_id, reason)


def _check_work_order_for_yarn(db: Session, work_order_id: int) -> WorkOrder:
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise NotFound(f"Work order {work_order_id} not found", field="work_order_id")
    # rolls take their yarn lineage from the weaving job; spinning and dyeing get none
    if wo.stage != Stage.weaving or wo.roll_id:
        raise Conflict(
            f"{wo.code} is {wo.stage}; yarn is issued to the order's weaving job",
            field="work_order_id",
            code="not_weaving",
        )
    if wo.status == WorkOrderStatus.done:
        raise Conflict(f"{wo.code} is already done", field="work_order_id")
    order = db.get(Order, wo.order_id)
    if order.status != OrderStatus.confirmed:
        raise Conflict(
            f"Order {order.code} is {order.status}; its jobs take no more yarn",
            field="work_order_id",
            code="order_not_open",
        )
    return wo


def _replay(db: Session, key: str | None, reason: MoveReason) -> StockMove | None:
    if not key:
        return None
    move = db.scalar(select(StockMove).where(StockMove.idempotency_key == key))
    if move and move.reason != reason:
        raise Conflict("Idempotency key already used for another action", field="idempotency_key")
    return move


# move reserved yarn from store to WIP for one work order; over-issue needs a reason
def issue_to_work_order(
    db: Session,
    work_order_id: int,
    yarn_batch_id: int,
    kg: Decimal,
    user_id: int,
    source: Source = Source.manual,
    idempotency_key: str | None = None,
    reason: str | None = None,
) -> StockMove:
    if done := _replay(db, idempotency_key, MoveReason.issue):
        return done
    wo = _check_work_order_for_yarn(db, work_order_id)
    batch = _lock_batch(db, yarn_batch_id)
    if batch.status != BatchStatus.approved:
        raise Conflict(
            f"{batch.code} is {batch.status}; only approved yarn can be issued",
            field="yarn_batch_id",
        )
    # only yarn the order's recipe and colour call for: wrong yarn means wrong lineage and cost
    order = db.get(Order, wo.order_id)
    if batch.yarn_item_id not in {n["yarn_item_id"] for n in order_needs(db, order)}:
        raise Conflict(
            f"{batch.code} is {item_label(batch.yarn_item)}; {order.code} does not use that yarn",
            field="yarn_batch_id",
            code="wrong_yarn",
        )
    kg = qty(kg)
    in_store = batch_kg_at(db, batch.id, LocationKind.store)
    all_reserved = reserved_by_batch(db, [batch.id]).get(batch.id, ZERO)
    mine = reserved_by_batch(db, [batch.id], order_id=wo.order_id).get(batch.id, ZERO)
    usable = in_store - (all_reserved - mine)  # never eat another order's kilos
    if kg > usable:
        raise Conflict(
            f"Only {usable} kg of {batch.code} is available to this order "
            f"({in_store} kg in store, {all_reserved - mine} kg reserved for other orders)",
            field="kg",
            code="insufficient_stock",
        )
    if kg > mine and not (reason and reason.strip()):
        raise BadRequest(
            f"{kg} kg is more than the {mine} kg reserved on {batch.code}. Give a reason.",
            field="reason",
        )

    left = kg
    for r in db.scalars(
        select(Reservation)
        .where(
            Reservation.yarn_batch_id == batch.id,
            Reservation.order_id == wo.order_id,
            Reservation.status == ReservationStatus.active,
        )
        .order_by(Reservation.id)
    ).all():
        if left <= 0:
            break
        take = min(r.kg, left)
        if take < r.kg:
            db.add(Reservation(yarn_batch_id=batch.id, order_id=wo.order_id, kg=r.kg - take))
            r.kg = take
        check_transition(RESERVATION_TRANSITIONS, r.status, ReservationStatus.consumed)
        r.status = ReservationStatus.consumed
        left -= take

    move = move_yarn(
        db,
        batch,
        kg,
        LocationKind.store,
        LocationKind.wip,
        MoveReason.issue,
        user_id,
        ref=("work_order", wo.id),
        source=source,
        idempotency_key=idempotency_key,
    )
    audit.record(
        db,
        user_id,
        "issue",
        "yarn_batches",
        batch.id,
        reason=reason.strip() if reason else None,
        data={"work_order": wo.code, "kg": str(kg), "over_issue": kg > mine},
    )
    return move


# unused yarn back from the floor to the store; becomes free stock again
def return_to_store(
    db: Session,
    work_order_id: int,
    yarn_batch_id: int,
    kg: Decimal,
    user_id: int,
    idempotency_key: str | None = None,
) -> StockMove:
    if done := _replay(db, idempotency_key, MoveReason.return_):
        return done
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise NotFound(f"Work order {work_order_id} not found", field="work_order_id")
    batch = _lock_batch(db, yarn_batch_id)
    kg = qty(kg)
    out = held_by_work_order(db, wo.id, batch.id)
    if kg > out:
        raise Conflict(
            f"{wo.code} holds only {out} kg of {batch.code}", field="kg", code="insufficient_stock"
        )
    move = move_yarn(
        db,
        batch,
        kg,
        LocationKind.wip,
        LocationKind.store,
        MoveReason.return_,
        user_id,
        ref=("work_order", wo.id),
        idempotency_key=idempotency_key,
    )
    audit.record(
        db, user_id, "return", "yarn_batches", batch.id, data={"work_order": wo.code, "kg": str(kg)}
    )
    return move


# per item kg that confirmed orders still need and have neither reserved nor been issued
def outstanding_need(db: Session) -> dict[int, Decimal]:
    orders = db.scalars(select(Order).where(Order.status == OrderStatus.confirmed)).all()
    reserved = defaultdict(lambda: ZERO)
    for order_id, item_id, kg in db.execute(
        select(Reservation.order_id, YarnBatch.yarn_item_id, func.sum(Reservation.kg))
        .join(YarnBatch, YarnBatch.id == Reservation.yarn_batch_id)
        .where(Reservation.status == ReservationStatus.active)
        .group_by(Reservation.order_id, YarnBatch.yarn_item_id)
    ).all():
        reserved[(order_id, item_id)] = kg
    need: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for order in orders:
        issued = issued_by_item(db, order.id)
        for line in order_needs(db, order):
            item_id = line["yarn_item_id"]
            if item_id is None:
                continue
            gap = line["kg_needed"] - reserved[(order.id, item_id)] - issued.get(item_id, ZERO)
            if gap > 0:
                need[item_id] += gap
    return {k: qty(v) for k, v in need.items()}


# R2 + R3: per yarn item, usable vs held stock and the early warning
def stock_overview(db: Session) -> dict:
    items = db.scalars(
        select(YarnItem)
        .where(YarnItem.active.is_(True))
        .order_by(YarnItem.fibre, YarnItem.count, YarnItem.colour)
    ).all()
    batches = db.execute(select(YarnBatch.id, YarnBatch.yarn_item_id, YarnBatch.status)).all()
    bal = balances(db)
    approved = [b for b, _, s in batches if s == BatchStatus.approved]
    reserved = reserved_by_batch(db, approved) if approved else {}
    need = outstanding_need(db)

    per = defaultdict(lambda: defaultdict(lambda: ZERO))
    unidentified = ZERO
    for batch_id, item_id, status in batches:
        where = bal.get(batch_id, {})
        if item_id is None:
            unidentified += sum((where.get(k, ZERO) for k in HOLDING), ZERO)
            continue
        if status == BatchStatus.approved:
            per[item_id]["on_hand"] += where.get(LocationKind.store, ZERO)
            per[item_id]["reserved"] += reserved.get(batch_id, ZERO)
        per[item_id]["inspection"] += where.get(LocationKind.inspection, ZERO)
        per[item_id]["quarantined"] += where.get(LocationKind.quarantine, ZERO)
        per[item_id]["wip"] += where.get(LocationKind.wip, ZERO)

    rows = []
    for item in items:
        p = per[item.id]
        free = p["on_hand"] - p["reserved"]
        projected = free - need.get(item.id, ZERO)
        if projected < 0:
            level = "short"
        elif projected < item.reorder_level_kg:
            level = "low"
        else:
            level = "ok"
        rows.append(
            {
                "yarn_item_id": item.id,
                "label": item_label(item),
                "fibre": item.fibre,
                "count": item.count,
                "colour": item.colour,
                "on_hand_kg": qty(p["on_hand"]),
                "reserved_kg": qty(p["reserved"]),
                "free_kg": qty(free),
                "inspection_kg": qty(p["inspection"]),
                "quarantined_kg": qty(p["quarantined"]),
                "wip_kg": qty(p["wip"]),
                "needed_by_orders_kg": qty(need.get(item.id, ZERO)),
                "projected_free_kg": qty(projected),
                "reorder_level_kg": qty(item.reorder_level_kg),
                "level": level,
            }
        )
    return {"items": rows, "unidentified_kg": qty(unidentified)}


# items whose projected free stock is under the reorder level (for dashboards)
def stock_warnings(db: Session) -> list[dict]:
    return [r for r in stock_overview(db)["items"] if r["level"] != "ok"]


# per recipe line: needed, reserved, issued, short, and which lots hold it
def order_allocation(db: Session, order_id: int) -> dict:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    issued = issued_by_item(db, order.id)
    res_rows = db.execute(
        select(Reservation, YarnBatch)
        .join(YarnBatch, YarnBatch.id == Reservation.yarn_batch_id)
        .where(
            Reservation.order_id == order.id,
            Reservation.status.in_([ReservationStatus.active, ReservationStatus.consumed]),
        )
        .order_by(Reservation.id)
    ).all()
    lines = []
    for need in order_needs(db, order):
        item_id = need["yarn_item_id"]
        mine = [(r, b) for r, b in res_rows if b.yarn_item_id == item_id]
        reserved = sum((r.kg for r, _ in mine if r.status == ReservationStatus.active), ZERO)
        done = issued.get(item_id, ZERO)
        lots: dict[int, dict] = {}
        for r, b in mine:
            lot = lots.setdefault(
                b.id,
                {
                    "yarn_batch_id": b.id,
                    "code": b.code,
                    "supplier_lot": b.supplier_lot,
                    "supplier": b.supplier.name,
                    "reserved_kg": ZERO,
                    "consumed_kg": ZERO,
                },
            )
            key = "reserved_kg" if r.status == ReservationStatus.active else "consumed_kg"
            lot[key] = qty(lot[key] + r.kg)
        short = need["kg_needed"] - reserved - done
        lines.append(
            {
                "fibre": need["fibre"],
                "count": need["count"],
                "colour": need["colour"],
                "yarn_item_id": item_id,
                "kg_needed": need["kg_needed"],
                "kg_reserved": qty(reserved),
                "kg_issued": qty(done),
                "kg_short": qty(max(short, ZERO)),
                "kg_free": free_stock(db, item_id) if item_id else ZERO,
                "lots": list(lots.values()),
                "mixed_lots": len(lots) > 1,
            }
        )
    return {
        "order_id": order.id,
        "code": order.code,
        "status": order.status,
        "lines": lines,
        "mixed_lots": any(line["mixed_lots"] for line in lines),
        "fully_covered": all(line["kg_short"] == 0 for line in lines),
    }


# what still has to be bought. Per order line: unreserved need, minus free stock (handed out
# earliest deadline first, so one free kilo is never promised twice), minus yarn already on order.
def to_buy(db: Session) -> list[dict]:
    rows = []
    free_left: dict[int, Decimal] = {}
    orders = db.scalars(
        select(Order)
        .where(Order.status == OrderStatus.confirmed)
        .order_by(Order.deadline, Order.id)
    ).all()
    for order in orders:
        for line in order_allocation(db, order.id)["lines"]:
            if line["kg_short"] <= 0:
                continue
            item_id = line["yarn_item_id"]
            on_order, from_free = ZERO, ZERO
            supplier_id, rate = None, None
            if item_id:
                free_left.setdefault(item_id, max(free_stock(db, item_id), ZERO))
                from_free = min(line["kg_short"], free_left[item_id])
                free_left[item_id] -= from_free
                for d in db.scalars(
                    select(ExpectedDelivery).where(
                        ExpectedDelivery.order_id == order.id,
                        ExpectedDelivery.yarn_item_id == item_id,
                        ExpectedDelivery.status.in_(
                            [ExpectedDeliveryStatus.open, ExpectedDeliveryStatus.partially_received]
                        ),
                    )
                ):
                    on_order += max(d.expected_kg - delivery_received_kg(db, d.id), ZERO)
                last = db.scalar(
                    select(YarnBatch)
                    .where(YarnBatch.yarn_item_id == item_id)
                    .order_by(YarnBatch.id.desc())
                )
                if last:
                    supplier_id, rate = last.supplier_id, last.unit_cost_paise_per_kg
            rows.append(
                {
                    "order_id": order.id,
                    "order_code": order.code,
                    "buyer": order.buyer.name,
                    "deadline": order.deadline,
                    "yarn_item_id": item_id,
                    "label": f"{line['fibre']} {line['count']} {line['colour']}",
                    "short_kg": line["kg_short"],
                    "free_cover_kg": qty(from_free),
                    "on_order_kg": qty(on_order),
                    "to_buy_kg": qty(max(line["kg_short"] - from_free - on_order, ZERO)),
                    "suggested_supplier_id": supplier_id,
                    "suggested_rate_paise_per_kg": rate,
                }
            )
    return rows


# ---------------------------------------------------------------- batch lifecycle (routes)


def list_batches(
    db: Session,
    page: Page,
    status: BatchStatus | None = None,
    yarn_item_id: int | None = None,
    q: str | None = None,
) -> dict:
    stmt = select(YarnBatch).order_by(YarnBatch.id.desc())
    if status:
        stmt = stmt.where(YarnBatch.status == status)
    if yarn_item_id:
        stmt = stmt.where(YarnBatch.yarn_item_id == yarn_item_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(YarnBatch.code.ilike(like), YarnBatch.supplier_lot.ilike(like)))
    return paginate(db, stmt, page)


def get_batch(db: Session, batch_id: int) -> YarnBatch:
    batch = db.get(YarnBatch, batch_id)
    if not batch:
        raise NotFound(f"Yarn batch {batch_id} not found")
    return batch


# batch + where its kilos are + every move + reservations + activity log
def batch_detail(db: Session, batch_id: int) -> dict:
    batch = get_batch(db, batch_id)
    src, dst = aliased(Location), aliased(Location)
    moves = db.execute(
        select(StockMove, src.code, dst.code, WorkOrder.code)
        .join(src, src.id == StockMove.from_location_id)
        .join(dst, dst.id == StockMove.to_location_id)
        .outerjoin(
            WorkOrder, (StockMove.ref_type == "work_order") & (WorkOrder.id == StockMove.ref_id)
        )
        .where(StockMove.yarn_batch_id == batch.id)
        .order_by(StockMove.at, StockMove.id)
    ).all()
    reservations = db.execute(
        select(Reservation, Order.code)
        .join(Order, Order.id == Reservation.order_id)
        .where(Reservation.yarn_batch_id == batch.id)
        .order_by(Reservation.id)
    ).all()
    activity = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "yarn_batches", AuditLog.entity_id == batch.id)
        .order_by(AuditLog.id)
    ).all()
    return {
        "batch": batch,
        "where": balances(db, [batch.id]).get(batch.id, {}),
        "moves": [
            {
                "id": m.id,
                "at": m.at,
                "qty": m.qty,
                "from_location": f,
                "to_location": t,
                "reason": m.reason,
                "work_order_code": wo,
                "source": m.source,
            }
            for m, f, t, wo in moves
        ],
        "reservations": [
            {"id": r.id, "order_id": r.order_id, "order_code": code, "kg": r.kg, "status": r.status}
            for r, code in reservations
        ],
        "activity": [
            {"at": a.created_at, "action": a.action, "reason": a.reason, "data": a.data}
            for a in activity
        ],
    }


# inspection -> store (approve), or quarantine -> store (owner release with reason)
def _to_store(db: Session, batch: YarnBatch, user: User, action: str, reason: str | None):
    if batch.yarn_item_id is None:
        raise Conflict("Identify the yarn before approving it", field="yarn_item_id")
    inspected = batch.status == BatchStatus.inspection
    frm = LocationKind.inspection if inspected else LocationKind.quarantine
    kg = batch_kg_at(db, batch.id, frm)
    if kg <= 0:
        raise Conflict("Nothing to approve yet: confirm the receipt first", field="status")
    _set_status(db, batch, BatchStatus.approved)
    move_yarn(db, batch, kg, frm, LocationKind.store, MoveReason(action), user.id)
    audit.record(db, user.id, action, "yarn_batches", batch.id, reason=reason, data={"kg": str(kg)})
    reserved = []
    order = db.get(Order, batch.order_id) if batch.order_id else None
    if order and order.status == OrderStatus.confirmed:
        reserved = reserve(db, order.id, user.id)
    db.commit()
    events.publish("stock", {"type": action, "id": batch.id})
    if reserved:
        events.publish("orders", {"type": "reserved", "id": order.id})
    return batch


def approve_batch(db: Session, batch_id: int, user: User) -> YarnBatch:
    batch = _lock_batch(db, batch_id)
    if batch.status == BatchStatus.quarantined:
        raise Conflict("Quarantined yarn needs an owner release with a reason", field="status")
    return _to_store(db, batch, user, "approve", None)


# owner only (router): quarantined -> approved, reason required
def release_batch(db: Session, batch_id: int, user: User, reason: str) -> YarnBatch:
    batch = _lock_batch(db, batch_id)
    if batch.status != BatchStatus.quarantined:
        raise Conflict(f"{batch.code} is {batch.status}, not quarantined", field="status")
    return _to_store(db, batch, user, "release", reason)


def quarantine_batch(db: Session, batch_id: int, user: User, reason: str) -> YarnBatch:
    batch = _lock_batch(db, batch_id)
    if batch.yarn_item_id is None:
        raise Conflict("Identify the yarn before quarantining it", field="yarn_item_id")
    frm = LocationKind.store if batch.status == BatchStatus.approved else LocationKind.inspection
    _set_status(db, batch, BatchStatus.quarantined)
    kg = batch_kg_at(db, batch.id, frm)
    if kg > 0:
        move_yarn(db, batch, kg, frm, LocationKind.quarantine, MoveReason.quarantine, user.id)
    freed = _release_reservations(
        db, Reservation.yarn_batch_id == batch.id, user.id, f"Batch quarantined: {reason}"
    )
    audit.record(db, user.id, "quarantine", "yarn_batches", batch.id, reason=reason)
    db.commit()
    events.publish("stock", {"type": "quarantine", "id": batch.id})
    if freed:
        events.publish("orders", {"type": "reservations_released", "id": batch.id})
    return batch


# bad yarn goes back to the supplier (same as the seed data does)
def reject_batch(db: Session, batch_id: int, user: User, reason: str) -> YarnBatch:
    batch = _lock_batch(db, batch_id)
    if batch.yarn_item_id is None:
        raise Conflict("Identify the yarn before rejecting it", field="yarn_item_id")
    _set_status(db, batch, BatchStatus.rejected)
    for frm in (LocationKind.inspection, LocationKind.quarantine):
        kg = batch_kg_at(db, batch.id, frm)
        if kg > 0:
            move_yarn(db, batch, kg, frm, LocationKind.supplier, MoveReason.return_, user.id)
    audit.record(db, user.id, "reject", "yarn_batches", batch.id, reason=reason)
    db.commit()
    events.publish("stock", {"type": "reject", "id": batch.id})
    return batch


# label was missing: store weighs and identifies the cones later
def identify_batch(
    db: Session, batch_id: int, user: User, yarn_item_id: int, supplier_lot: str | None
) -> YarnBatch:
    batch = _lock_batch(db, batch_id)
    item = db.get(YarnItem, yarn_item_id)
    if not item or not item.active:
        raise NotFound("Yarn item not found or inactive", field="yarn_item_id")
    receipt = db.get(Receipt, batch.receipt_id)
    delivery = (
        db.get(ExpectedDelivery, receipt.expected_delivery_id)
        if receipt.expected_delivery_id
        else None
    )
    mismatch = delivery is not None and delivery.yarn_item_id != item.id
    _set_status(db, batch, BatchStatus.quarantined if mismatch else BatchStatus.inspection)
    batch.yarn_item_id = item.id
    batch.supplier_lot = supplier_lot
    if mismatch:
        note = f"Identified as {item_label(item)}, expected {item_label(delivery.yarn_item)}"
        batch.mismatch_notes = "; ".join(filter(None, [batch.mismatch_notes, note]))
        kg = batch_kg_at(db, batch.id, LocationKind.inspection)
        if kg > 0:
            move_yarn(
                db,
                batch,
                kg,
                LocationKind.inspection,
                LocationKind.quarantine,
                MoveReason.quarantine,
                user.id,
            )
    audit.record(db, user.id, "identify", "yarn_batches", batch.id, data={"yarn_item_id": item.id})
    db.commit()
    events.publish("stock", {"type": "identify", "id": batch.id})
    return batch


# store screen: scan a work order, see its reserved batches oldest first (FIFO)
def issue_plan(db: Session, work_order_code: str) -> dict:
    wo = db.scalar(select(WorkOrder).where(WorkOrder.code == work_order_code.strip().upper()))
    if not wo:
        raise NotFound(f"No work order {work_order_code.strip()}", field="work_order")
    order = db.get(Order, wo.order_id)
    item_ids = [n["yarn_item_id"] for n in order_needs(db, order) if n["yarn_item_id"]]
    batches = db.scalars(
        select(YarnBatch)
        .join(Receipt, Receipt.id == YarnBatch.receipt_id)
        .where(YarnBatch.yarn_item_id.in_(item_ids), YarnBatch.status == BatchStatus.approved)
        .order_by(Receipt.confirmed_at, YarnBatch.id)
    ).all()
    ids = [b.id for b in batches]
    bal = balances(db, ids)
    all_res = reserved_by_batch(db, ids) if ids else {}
    mine = reserved_by_batch(db, ids, order_id=order.id) if ids else {}
    issued_ids = db.scalars(
        select(StockMove.yarn_batch_id)
        .where(StockMove.ref_type == "work_order", StockMove.ref_id == wo.id)
        .distinct()
    ).all()
    lines = []
    for b in batches:
        in_store = bal.get(b.id, {}).get(LocationKind.store, ZERO)
        lines.append(
            {
                "yarn_batch_id": b.id,
                "code": b.code,
                "supplier_lot": b.supplier_lot,
                "label": item_label(b.yarn_item),
                "supplier": b.supplier.name,
                "received_at": b.receipt.confirmed_at,
                "store_kg": in_store,
                "reserved_for_order_kg": mine.get(b.id, ZERO),
                "free_kg": qty(in_store - all_res.get(b.id, ZERO)),
                "issued_to_work_order_kg": issued_to_work_order(db, wo.id, b.id),
            }
        )
    reserved_first = [ln for ln in lines if ln["reserved_for_order_kg"] > 0]
    others = [ln for ln in lines if ln["reserved_for_order_kg"] == 0 and ln["free_kg"] > 0]
    on_floor = [
        {"yarn_batch_id": b, "code": db.get(YarnBatch, b).code, "kg": k}
        for b in issued_ids
        if (k := held_by_work_order(db, wo.id, b)) > 0
    ]
    return {
        "work_order": {
            "id": wo.id,
            "code": wo.code,
            "stage": wo.stage,
            "status": wo.status,
            "order_id": order.id,
            "order_code": order.code,
        },
        "reserved": reserved_first,
        "free": others,
        "on_floor": on_floor,
    }


# issue / return routes: shared service + commit + live update
def issue(db: Session, user: User, data) -> StockMove:
    move = issue_to_work_order(
        db,
        data.work_order_id,
        data.yarn_batch_id,
        data.kg,
        user.id,
        source=data.source,
        idempotency_key=data.idempotency_key,
        reason=data.reason,
    )
    db.commit()
    events.publish("stock", {"type": "issue", "id": move.yarn_batch_id})
    return move


def give_back(db: Session, user: User, data) -> StockMove:
    move = return_to_store(
        db, data.work_order_id, data.yarn_batch_id, data.kg, user.id, data.idempotency_key
    )
    db.commit()
    events.publish("stock", {"type": "return", "id": move.yarn_batch_id})
    return move
