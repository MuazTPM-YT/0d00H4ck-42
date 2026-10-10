# small builders for dispatch, tracking and finance tests: one order, its looms, its rolls
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Stage, Unit
from app.modules.inventory.models import ItemKind, MoveReason, StockMove
from app.modules.masters.models import (
    Buyer,
    FabricRecipe,
    FabricType,
    FabricTypeStage,
    Location,
    LocationKind,
    Machine,
    Shift,
    WageType,
    Worker,
)
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrder, WorkOrderStatus
from app.modules.quality.models import Roll, RollStatus

NOW = datetime.now(UTC).replace(microsecond=0)
LOCATIONS = [
    ("SUP", LocationKind.supplier),
    ("YS-01", LocationKind.store),
    ("WIP", LocationKind.wip),
    ("PROD", LocationKind.consumed),
    ("FG-01", LocationKind.finished),
    ("REJ", LocationKind.rejected),
    ("DISP", LocationKind.dispatched),
]


class Mill:
    def __init__(self, db: Session):
        self.db = db
        self.n = 0
        self.loc = {}
        for code, kind in LOCATIONS:
            row = db.scalar(select(Location).where(Location.code == code))
            if not row:
                row = Location(code=code, name=code, kind=kind)
                db.add(row)
            self.loc[code] = row
        self.buyer = Buyer(code="MB", name="Mill Buyer", gstin="27AAACM4321K1Z3", city="Mumbai")
        self.fabric = FabricType(
            code="MSHIRT",
            name="Mill Shirting",
            width_cm=Decimal(150),
            gsm=Decimal(100),
            process_loss_pct=Decimal(0),
            stages=[FabricTypeStage(seq=1, stage=Stage.weaving)],
            recipe=[FabricRecipe(fibre="Cotton", count="Ne 40/1", share_pct=Decimal(100))],
        )
        self.loom = Machine(
            code="LM-T1",
            name="Test loom",
            type=Stage.weaving,
            hourly_cost_paise=30000,
            rated_output_per_hour=Decimal(18),
            output_unit=Unit.m,
        )
        self.shift = Shift(code="A", name="Shift A", start_time=time(6), end_time=time(14))
        self.weaver = Worker(
            code="W-T9", name="Weaver", wage_type=WageType.piece, piece_rate_paise_per_m=400
        )
        db.add_all([self.buyer, self.fabric, self.loom, self.shift, self.weaver])
        db.flush()

    def order(
        self,
        qty_m: int = 300,
        rate: int = 18500,
        status: OrderStatus = OrderStatus.confirmed,
        deadline: date | None = None,
    ) -> Order:
        self.n += 1
        o = Order(
            code=f"SO-T{self.n}",
            buyer_id=self.buyer.id,
            fabric_type_id=self.fabric.id,
            colour="Navy",
            qty_m=Decimal(qty_m),
            rate_paise_per_m=rate,
            deadline=deadline or NOW.date() + timedelta(days=20),
            status=status,
            confirmed_at=NOW - timedelta(days=10) if status != OrderStatus.draft else None,
        )
        self.db.add(o)
        self.db.flush()
        return o

    def work_order(
        self, order: Order, status: WorkOrderStatus = WorkOrderStatus.done, seq: int = 1
    ) -> WorkOrder:
        self.n += 1
        wo = WorkOrder(
            code=f"WO-T{self.n}",
            order_id=order.id,
            stage=Stage.weaving,
            seq=seq,
            machine_id=self.loom.id if status != WorkOrderStatus.waiting else None,
            planned_qty=order.qty_m,
            unit=Unit.m,
            status=status,
            started_at=NOW - timedelta(days=5) if status != WorkOrderStatus.waiting else None,
            finished_at=NOW - timedelta(days=1) if status == WorkOrderStatus.done else None,
        )
        self.db.add(wo)
        self.db.flush()
        return wo

    # roll woven on the test loom; passed rolls get a shelf move PROD -> WIP -> FG
    def roll(
        self,
        wo: WorkOrder,
        length: int | str,
        status: RollStatus = RollStatus.passed,
        band: str | None = "A",
        days_ago: int = 1,
    ) -> Roll:
        self.n += 1
        passed = status in (RollStatus.passed, RollStatus.dispatched)
        where = {RollStatus.passed: "FG-01", RollStatus.rejected: "REJ"}.get(status, "WIP")
        r = Roll(
            code=f"R-T{self.n:04d}",
            order_id=wo.order_id,
            work_order_id=wo.id,
            loom_machine_id=self.loom.id,
            shift_id=self.shift.id,
            weaver_id=self.weaver.id,
            length_m=Decimal(length),
            status=status,
            shade_band=band if passed else None,
            location_id=self.loc[where].id,
            passed_at=NOW - timedelta(days=days_ago) if passed else None,
        )
        self.db.add(r)
        self.db.flush()
        self.move(r, "PROD", "WIP", MoveReason.produce)
        if where != "WIP":
            reason = MoveReason.qc_pass if where == "FG-01" else MoveReason.qc_reject
            self.move(r, "WIP", where, reason)
        return r

    def move(self, roll: Roll, frm: str, to: str, reason: MoveReason) -> None:
        self.db.add(
            StockMove(
                item_kind=ItemKind.fabric,
                roll_id=roll.id,
                qty=roll.length_m,
                unit=Unit.m,
                from_location_id=self.loc[frm].id,
                to_location_id=self.loc[to].id,
                reason=reason,
            )
        )
        self.db.flush()
