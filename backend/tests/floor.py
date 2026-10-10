# small mill for production and workforce tests: 2 looms, 1 jigger, 3 shifts, 2 yarn batches
from datetime import UTC, datetime, time
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.enums import Stage, Unit
from app.modules.auth.models import Role, User
from app.modules.inventory.models import (
    BatchStatus,
    ItemKind,
    MoveReason,
    Receipt,
    StockMove,
    YarnBatch,
)
from app.modules.masters.models import (
    FabricRecipe,
    FabricType,
    FabricTypeStage,
    Location,
    LocationKind,
    Machine,
    Shift,
    Supplier,
    WageType,
    Worker,
    YarnItem,
)
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.service import create_work_orders


def build_floor(db: Session, buyer, dyed_fabric) -> SimpleNamespace:
    loc = {
        kind: Location(code=kind.upper()[:8], name=kind, kind=kind)
        for kind in (
            LocationKind.supplier,
            LocationKind.store,
            LocationKind.wip,
            LocationKind.consumed,
        )
    }
    db.add_all(loc.values())
    shifts = [
        Shift(code="TA", name="A", start_time=time(6), end_time=time(14)),
        Shift(code="TB", name="B", start_time=time(14), end_time=time(22)),
        Shift(code="TC", name="C", start_time=time(22), end_time=time(6)),
    ]
    db.add_all(shifts)

    def machine(code, stage, unit):
        return Machine(
            code=code,
            name=code,
            type=stage,
            hourly_cost_paise=30000,
            rated_output_per_hour=Decimal(18),
            output_unit=unit,
        )

    loom1, loom2 = machine("LM-T1", Stage.weaving, Unit.m), machine("LM-T2", Stage.weaving, Unit.m)
    jigger = machine("DYE-T1", Stage.dyeing, Unit.m)
    db.add_all([loom1, loom2, jigger])
    weaver = Worker(code="W-T1", name="Weaver", wage_type=WageType.daily, daily_rate_paise=65000)
    helper = Worker(code="W-T2", name="Helper", wage_type=WageType.daily, daily_rate_paise=65000)
    db.add_all([weaver, helper])
    shirting = FabricType(
        code="TSHIRT",
        name="Test Shirting",
        width_cm=Decimal(147),
        gsm=Decimal(115),
        process_loss_pct=Decimal(5),
        stages=[FabricTypeStage(seq=1, stage=Stage.weaving)],
        recipe=[FabricRecipe(fibre="Cotton", count="Ne 40/1", share_pct=Decimal(100))],
    )
    db.add(shirting)
    supplier = Supplier(code="TSUP", name="Test Spinner")
    item = YarnItem(fibre="Cotton", count="Ne 40/1", colour="Raw White")
    db.add_all([supplier, item])
    db.flush()
    receipt = Receipt(code="RC-T1", supplier_id=supplier.id)
    db.add(receipt)
    db.flush()
    batches = [
        YarnBatch(
            code=f"YB-T{i}",
            yarn_item_id=item.id,
            supplier_id=supplier.id,
            supplier_lot=f"LOT-{i}",
            receipt_id=receipt.id,
            received_kg=Decimal(500),
            unit_cost_paise_per_kg=28500,
            status=BatchStatus.approved,
        )
        for i in (1, 2)
    ]
    db.add_all(batches)
    supervisor = User(name="Sup", email="sup@floor.test", role=Role.supervisor, password_hash="x")
    db.add(supervisor)

    def order(fabric, code):
        o = Order(
            code=code,
            buyer_id=buyer.id,
            fabric_type_id=fabric.id,
            colour="Raw White",
            qty_m=Decimal(600),
            rate_paise_per_m=20000,
            deadline="2026-12-01",
            status=OrderStatus.confirmed,
            confirmed_at=datetime.now(UTC),
        )
        db.add(o)
        db.flush()
        return o, create_work_orders(db, o.id, None)

    shirt_order, (shirt_weave,) = order(shirting, "SO-T1")
    dyed_order, (dyed_weave, dyed_dye) = order(dyed_fabric, "SO-T2")
    db.commit()

    # store -> WIP issue, the move shape inventory.issue_to_work_order writes
    def issue(wo, batch, kg):
        db.add(
            StockMove(
                at=datetime.now(UTC),
                item_kind=ItemKind.yarn,
                yarn_batch_id=batch.id,
                qty=Decimal(kg),
                unit=Unit.kg,
                from_location_id=loc[LocationKind.store].id,
                to_location_id=loc[LocationKind.wip].id,
                reason=MoveReason.issue,
                ref_type="work_order",
                ref_id=wo.id,
            )
        )
        db.commit()

    return SimpleNamespace(
        loc=loc,
        shifts=shifts,
        loom1=loom1,
        loom2=loom2,
        jigger=jigger,
        weaver=weaver,
        helper=helper,
        batches=batches,
        supervisor=supervisor,
        shirting=shirting,
        shirt_order=shirt_order,
        shirt_weave=shirt_weave,
        dyed_order=dyed_order,
        dyed_weave=dyed_weave,
        dyed_dye=dyed_dye,
        issue=issue,
    )
