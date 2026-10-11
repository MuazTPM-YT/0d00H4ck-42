from datetime import UTC, datetime, time
from decimal import Decimal
from itertools import count

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Stage, Unit
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.inventory.models import BatchStatus, MoveReason, Receipt, ReceiptStatus, YarnBatch
from app.modules.inventory.service import move_yarn
from app.modules.masters.models import (
    FabricRecipe,
    FabricType,
    FabricTypeStage,
    Location,
    LocationKind,
    Machine,
    Shift,
    Supplier,
    YarnItem,
)
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrder
from app.modules.quality.models import Roll, RollStatus

_seq = count(1)
KINDS = (
    LocationKind.supplier,
    LocationKind.inspection,
    LocationKind.quarantine,
    LocationKind.store,
    LocationKind.wip,
    LocationKind.consumed,
)


def uid() -> int:
    return next(_seq)


def ensure_locations(db: Session) -> None:
    for kind in KINDS:
        code = f"T-{kind.value[:10].upper()}"
        if not db.scalar(select(Location).where(Location.code == code)):
            db.add(Location(code=code, name=f"Test {kind}", kind=kind))
    db.flush()


def make_supplier(db: Session, code: str = "TSUP") -> Supplier:
    row = db.scalar(select(Supplier).where(Supplier.code == code))
    if not row:
        row = Supplier(code=code, name=f"Test Spinners {code}")
        db.add(row)
        db.flush()
    return row


def make_item(db: Session, count_: str, colour: str, reorder: int = 0, fibre="Cotton") -> YarnItem:
    row = YarnItem(fibre=fibre, count=count_, colour=colour, reorder_level_kg=Decimal(reorder))
    db.add(row)
    db.flush()
    return row


def plain_fabric(db: Session, count_: str = "Ne 40/1", fibre="Cotton", code="TSHIRT") -> FabricType:
    # 150 cm, 120 gsm, 10% loss, +5% process allowance: 1000 m needs 210 kg yarn
    row = FabricType(
        code=code,
        name="Test Shirting",
        width_cm=Decimal(150),
        gsm=Decimal(120),
        process_loss_pct=Decimal(10),
        stages=[FabricTypeStage(seq=1, stage=Stage.weaving)],
        recipe=[FabricRecipe(fibre=fibre, count=count_, share_pct=Decimal(100))],
    )
    db.add(row)
    db.flush()
    return row


def make_order(db, buyer, fabric, colour, metres, status=OrderStatus.confirmed) -> Order:
    order = Order(
        code=f"SO-T{uid()}",
        buyer_id=buyer.id,
        fabric_type_id=fabric.id,
        colour=colour,
        qty_m=Decimal(metres),
        rate_paise_per_m=20000,
        deadline="2027-01-31",
        status=status,
        confirmed_at=None if status == OrderStatus.draft else datetime.now(UTC),
    )
    db.add(order)
    db.flush()
    return order


# a batch already received; approved ones sit in store, others where their status says
def make_batch(
    db: Session,
    supplier: Supplier,
    item: YarnItem,
    kg,
    status=BatchStatus.approved,
    order_id=None,
) -> YarnBatch:
    n = uid()
    receipt = Receipt(
        code=f"RC-T{n}",
        supplier_id=supplier.id,
        status=ReceiptStatus.confirmed,
        confirmed_at=datetime.now(UTC),
    )
    db.add(receipt)
    db.flush()
    batch = YarnBatch(
        code=f"YB-T{n}",
        yarn_item_id=item.id,
        supplier_id=supplier.id,
        supplier_lot=f"LOT-{n}",
        receipt_id=receipt.id,
        received_kg=Decimal(kg),
        unit_cost_paise_per_kg=28000,
        status=status,
        order_id=order_id,
    )
    db.add(batch)
    db.flush()
    where = {
        BatchStatus.approved: LocationKind.store,
        BatchStatus.quarantined: LocationKind.quarantine,
    }.get(status, LocationKind.inspection)
    move_yarn(db, batch, Decimal(kg), LocationKind.supplier, where, MoveReason.receipt, None)
    return batch


def spun_fabric(db: Session, count_: str = "Ne 40/1", code="TSPUN") -> FabricType:
    # same size as plain_fabric, but the route starts at spinning: yarn goes there first
    row = FabricType(
        code=code,
        name="Test Spun Shirting",
        width_cm=Decimal(150),
        gsm=Decimal(120),
        process_loss_pct=Decimal(10),
        stages=[
            FabricTypeStage(seq=1, stage=Stage.spinning),
            FabricTypeStage(seq=2, stage=Stage.weaving),
        ],
        recipe=[FabricRecipe(fibre="Cotton", count=count_, share_pct=Decimal(100))],
    )
    db.add(row)
    db.flush()
    return row


def make_machine(db: Session, stage=Stage.weaving) -> Machine:
    row = Machine(
        code=f"TM-{uid()}",
        name="Test machine",
        type=stage,
        hourly_cost_paise=30000,
        rated_output_per_hour=Decimal(18),
        output_unit=Unit.kg if stage == Stage.spinning else Unit.m,
    )
    db.add(row)
    db.flush()
    return row


# a passed roll of the order on a dispatch in the given status
def ship_roll(db: Session, order: Order, length_m, status=DispatchStatus.confirmed) -> Dispatch:
    wo = db.scalar(
        select(WorkOrder).where(
            WorkOrder.order_id == order.id,
            WorkOrder.stage == Stage.weaving,
            WorkOrder.roll_id.is_(None),
        )
    )
    shift = Shift(code=f"S{uid()}"[:5], name="Test shift", start_time=time(6), end_time=time(14))
    db.add(shift)
    db.flush()
    loc = db.scalar(select(Location.id).where(Location.kind == LocationKind.wip))
    roll = Roll(
        code=f"R-T{uid()}",
        order_id=order.id,
        work_order_id=wo.id,
        loom_machine_id=make_machine(db).id,
        shift_id=shift.id,
        length_m=Decimal(length_m),
        status=RollStatus.dispatched if status == DispatchStatus.confirmed else RollStatus.passed,
        location_id=loc,
        passed_at=datetime.now(UTC),
    )
    dispatch = Dispatch(
        code=f"DN-T{uid()}",
        order_id=order.id,
        buyer_id=order.buyer_id,
        vehicle_no="KA-01-AB-1234",
        status=status,
        confirmed_at=datetime.now(UTC) if status == DispatchStatus.confirmed else None,
    )
    db.add_all([roll, dispatch])
    db.flush()
    db.add(DispatchRoll(dispatch_id=dispatch.id, roll_id=roll.id))
    db.flush()
    return dispatch
