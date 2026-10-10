# base demo data: masters + one record in every status. Safe to run twice.
# run: make seed   (cd backend && PYTHONPATH=. uv run python ../scripts/seed.py)
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  registers every table
from app.core.codes import next_code
from app.core.db import SessionLocal
from app.core.enums import Source, Stage, Unit
from app.core.security import hash_password
from app.core.units import line_amount_paise, qty
from app.modules.analytics.models import Insight, InsightStatus, Severity
from app.modules.auth.models import Role, User
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.finance.models import (
    Expense,
    ExpenseCategory,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentMode,
    WageLine,
    WageRun,
    WageRunStatus,
)
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
from app.modules.masters.models import (
    Buyer,
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
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    ProductionLog,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.production.service import create_work_orders
from app.modules.quality.models import QcCheck, QcDecision, Roll, RollBatch, RollEvent, RollStatus
from app.modules.workforce.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    CrewAssignment,
)

DEMO_PASSWORD = "demo1234"
NOW = datetime.now(UTC).replace(microsecond=0)
TODAY = NOW.date()


def get_or_create(db: Session, model, key: dict, **fields):
    row = db.scalar(select(model).filter_by(**key))
    if row:
        return row
    row = model(**key, **fields)
    db.add(row)
    db.flush()
    return row


def seed_masters(db: Session) -> None:
    for code, name, kind in [
        ("SUP", "Supplier (virtual)", LocationKind.supplier),
        ("INSP", "Gate inspection bay", LocationKind.inspection),
        ("QUAR", "Quarantine cage", LocationKind.quarantine),
        ("YS-01", "Yarn store", LocationKind.store),
        ("WIP", "Production floor", LocationKind.wip),
        ("PROD", "Production (virtual: yarn in, fabric out)", LocationKind.consumed),
        ("FG-01", "Finished goods shelf", LocationKind.finished),
        ("REJ", "Rejected goods", LocationKind.rejected),
        ("DISP", "Dispatched (virtual)", LocationKind.dispatched),
    ]:
        get_or_create(db, Location, {"code": code}, name=name, kind=kind)

    pw = hash_password(DEMO_PASSWORD)
    for role, name in [
        (Role.owner, "Rajesh Agarwal"),
        (Role.store, "Suresh Naik"),
        (Role.supervisor, "Manjunath Gowda"),
        (Role.qc, "Priya Raman"),
        (Role.dispatch, "Imran Shaikh"),
        (Role.accounts, "Kavitha Rao"),
        (Role.sales, "Arjun Mehta"),
    ]:
        get_or_create(
            db, User, {"email": f"{role}@everest.local"}, name=name, role=role, password_hash=pw
        )

    for code, name, gstin, city in [
        ("KSM", "Kaveri Spinning Mills", "33AABCK1234F1Z5", "Erode"),
        ("SLY", "Sri Lakshmi Yarns", "33AAFCS5678G1Z2", "Tiruppur"),
        ("DCS", "Deccan Cotton Spinners", "27AACCD9012H1Z8", "Ichalkaranji"),
    ]:
        get_or_create(
            db,
            Supplier,
            {"code": code},
            name=name,
            gstin=gstin,
            city=city,
            phone="+91 98450 1" + gstin[8:12],
        )

    for code, name, gstin, contact, city in [
        ("MEHTA", "Mehta Garments Pvt Ltd", "27AAACM4321K1Z3", "Nikhil Mehta", "Mumbai"),
        ("SHARMA", "Sharma Apparels", "07AAJFS8765L1Z9", "Pooja Sharma", "New Delhi"),
        ("IYER", "Iyer Exports", "33AADFI2468M1Z1", "Venkat Iyer", "Chennai"),
        ("PATEL", "Patel Fashion House", "24AAEFP1357N1Z6", "Hetal Patel", "Ahmedabad"),
        ("GOWDA", "Gowda Uniforms", "29AAGFG9753P1Z4", "Ramesh Gowda", "Bengaluru"),
    ]:
        get_or_create(
            db,
            Buyer,
            {"code": code},
            name=name,
            gstin=gstin,
            contact_name=contact,
            city=city,
            email=f"orders@{code.lower()}.example.in",
        )

    for count in ("Ne 30/1", "Ne 40/1"):
        for colour in ("Raw White", "Navy", "Black"):
            get_or_create(
                db,
                YarnItem,
                {"fibre": "Cotton", "count": count, "colour": colour},
                reorder_level_kg=Decimal(500 if colour == "Raw White" else 250),
            )

    for code, name, width, gsm, loss, route, recipe in [
        (
            "SHIRT40",
            "Cotton Shirting 40s",
            147,
            115,
            5,
            [Stage.weaving],
            [("Cotton", "Ne 40/1", 100)],
        ),
        (
            "DRILL30",
            "Cotton Drill 30s",
            152,
            220,
            8,
            [Stage.spinning, Stage.weaving],
            [("Cotton", "Ne 30/1", 100)],
        ),
        (
            "POPDYE",
            "Piece-dyed Poplin",
            150,
            125,
            10,
            [Stage.weaving, Stage.dyeing],
            [("Cotton", "Ne 40/1", 60), ("Cotton", "Ne 30/1", 40)],
        ),
    ]:
        if db.scalar(select(FabricType).filter_by(code=code)):
            continue
        db.add(
            FabricType(
                code=code,
                name=name,
                width_cm=Decimal(width),
                gsm=Decimal(gsm),
                process_loss_pct=Decimal(loss),
                stages=[FabricTypeStage(seq=i + 1, stage=s) for i, s in enumerate(route)],
                recipe=[FabricRecipe(fibre=f, count=c, share_pct=Decimal(p)) for f, c, p in recipe],
            )
        )

    machines = (
        [(f"SPN-0{i}", f"Ring frame {i}", Stage.spinning, 45000, 25, Unit.kg) for i in (1, 2)]
        + [(f"LM-0{i}", f"Air-jet loom {i}", Stage.weaving, 30000, 18, Unit.m) for i in range(1, 7)]
        + [(f"DYE-0{i}", f"Jigger dyeing {i}", Stage.dyeing, 90000, 120, Unit.m) for i in (1, 2)]
    )
    for code, name, stage, cost, rated, unit in machines:
        get_or_create(
            db,
            Machine,
            {"code": code},
            name=name,
            type=stage,
            hourly_cost_paise=cost,
            rated_output_per_hour=Decimal(rated),
            output_unit=unit,
        )

    names = [
        "Ramesh Kumar",
        "Lakshmi Devi",
        "Mohammed Rafiq",
        "Anitha S",
        "Venkatesh R",
        "Sunita Patil",
        "Basavaraj H",
        "Fatima Begum",
        "Prakash Shetty",
        "Geetha M",
        "Raju Nayak",
        "Shobha K",
        "Abdul Kareem",
        "Meena Kumari",
        "Shivanna B",
        "Kavya Reddy",
        "Mahesh Gowda",
        "Nirmala D",
        "Santosh Jadhav",
        "Rekha P",
        "Imtiaz Ali",
        "Sowmya N",
        "Girish T",
        "Pushpa L",
    ]
    for i, name in enumerate(names, start=1):
        piece = 9 <= i <= 16  # loom weavers paid per metre
        get_or_create(
            db,
            Worker,
            {"code": f"W-{i:03d}"},
            name=name,
            wage_type=WageType.piece if piece else WageType.daily,
            daily_rate_paise=None if piece else 65000,
            piece_rate_paise_per_m=400 if piece else None,
        )

    for code, start, end in [
        ("A", time(6), time(14)),
        ("B", time(14), time(22)),
        ("C", time(22), time(6)),
    ]:
        get_or_create(
            db, Shift, {"code": code}, name=f"Shift {code}", start_time=start, end_time=end
        )
    db.flush()


def seed_demo(db: Session) -> None:
    loc = {row.code: row for row in db.scalars(select(Location))}
    user = {row.role: row for row in db.scalars(select(User))}
    sup = {row.code: row for row in db.scalars(select(Supplier))}
    buyer = {row.code: row for row in db.scalars(select(Buyer))}
    yarn = {(r.count, r.colour): r for r in db.scalars(select(YarnItem))}
    fabric = {row.code: row for row in db.scalars(select(FabricType))}
    mc = {row.code: row for row in db.scalars(select(Machine))}
    worker = {row.code: row for row in db.scalars(select(Worker))}
    shift = {row.code: row for row in db.scalars(select(Shift))}
    store_id = user[Role.store].id

    def move(kind, item_id, q, frm, to, reason, at, ref=(None, None), source=Source.manual):
        db.add(
            StockMove(
                at=at,
                item_kind=kind,
                qty=qty(q),
                yarn_batch_id=item_id if kind == ItemKind.yarn else None,
                roll_id=item_id if kind == ItemKind.fabric else None,
                unit=Unit.kg if kind == ItemKind.yarn else Unit.m,
                from_location_id=loc[frm].id,
                to_location_id=loc[to].id,
                reason=reason,
                ref_type=ref[0],
                ref_id=ref[1],
                user_id=store_id,
                source=source,
            )
        )

    # --- orders first: deliveries, batches and reservations point at them
    def order(buyer_code, fabric_code, colour, qty_m, rate_rupees, days, status):
        o = Order(
            code=next_code(db, "SO"),
            buyer_id=buyer[buyer_code].id,
            fabric_type_id=fabric[fabric_code].id,
            colour=colour,
            qty_m=Decimal(qty_m),
            rate_paise_per_m=rate_rupees * 100,
            deadline=TODAY + timedelta(days=days),
            status=status,
            confirmed_at=None
            if status in (OrderStatus.draft, OrderStatus.cancelled)
            else NOW - timedelta(days=10),
        )
        db.add(o)
        db.flush()
        return o

    so_closed = order("IYER", "SHIRT40", "Raw White", 225, 180, -5, OrderStatus.closed)
    so_shirt = order("MEHTA", "SHIRT40", "Navy", 1200, 185, 12, OrderStatus.confirmed)
    so_dyed = order("SHARMA", "POPDYE", "Maroon", 800, 240, 20, OrderStatus.confirmed)
    so_drill = order("GOWDA", "DRILL30", "Raw White", 1000, 210, 25, OrderStatus.confirmed)
    order("PATEL", "SHIRT40", "Black", 600, 190, 30, OrderStatus.draft)
    so_cancel = order("PATEL", "POPDYE", "Bottle Green", 400, 245, 15, OrderStatus.cancelled)

    # --- expected deliveries, one per status
    for s, y, kg, status in [
        ("KSM", ("Ne 40/1", "Raw White"), 1200, ExpectedDeliveryStatus.received),
        ("SLY", ("Ne 30/1", "Navy"), 1000, ExpectedDeliveryStatus.partially_received),
        ("DCS", ("Ne 30/1", "Black"), 800, ExpectedDeliveryStatus.open),
        ("SLY", ("Ne 40/1", "Black"), 300, ExpectedDeliveryStatus.cancelled),
    ]:
        db.add(
            ExpectedDelivery(
                supplier_id=sup[s].id,
                yarn_item_id=yarn[y].id,
                expected_kg=Decimal(kg),
                rate_paise_per_kg=28500,
                expected_date=TODAY + timedelta(days=3),
                status=status,
            )
        )

    # --- receipts and batches, one batch per status
    def receipt(s, bill_no, amount, status, days_ago):
        r = Receipt(
            code=next_code(db, "RC"),
            supplier_id=sup[s].id,
            vehicle_no="KA-05-MN-4521",
            bill_no=bill_no,
            bill_amount_paise=amount,
            status=status,
            confirmed_at=NOW - timedelta(days=days_ago)
            if status == ReceiptStatus.confirmed
            else None,
        )
        db.add(r)
        db.flush()
        return r

    rc1 = receipt("KSM", "KSM/24-25/1182", 45_885_000, ReceiptStatus.confirmed, 14)
    rc2 = receipt("SLY", "SLY/0931", 33_480_000, ReceiptStatus.confirmed, 6)
    rc3 = receipt("DCS", "DCS/7710", 0, ReceiptStatus.draft, 0)

    def batch(rc, s, y, lot, kg, cost, status, notes=None):
        b = YarnBatch(
            code=next_code(db, "YB"),
            yarn_item_id=yarn[y].id if y else None,
            supplier_id=sup[s].id,
            supplier_lot=lot,
            receipt_id=rc.id,
            received_kg=Decimal(kg),
            unit_cost_paise_per_kg=cost,
            status=status,
            mismatch_notes=notes,
        )
        db.add(b)
        db.flush()
        at = NOW - timedelta(days=14 if rc is rc1 else 6)
        move(ItemKind.yarn, b.id, kg, "SUP", "INSP", MoveReason.receipt, at, ("receipt", rc.id))
        then = {
            BatchStatus.approved: ("YS-01", MoveReason.approve),
            BatchStatus.quarantined: ("QUAR", MoveReason.quarantine),
            BatchStatus.rejected: ("SUP", MoveReason.return_),
        }.get(status)
        if then:
            move(
                ItemKind.yarn,
                b.id,
                kg,
                "INSP",
                then[0],
                then[1],
                at + timedelta(hours=3),
                ("yarn_batch", b.id),
            )
        return b

    yb_white40 = batch(
        rc1, "KSM", ("Ne 40/1", "Raw White"), "KSM-L2291", 1200, 28500, BatchStatus.approved
    )
    batch(rc1, "KSM", ("Ne 30/1", "Raw White"), "KSM-L2295", 900, 26500, BatchStatus.approved)
    yb_navy40 = batch(
        rc2, "SLY", ("Ne 40/1", "Navy"), "SLY-N0412", 600, 31000, BatchStatus.approved
    )
    batch(
        rc2,
        "SLY",
        ("Ne 30/1", "Black"),
        "SLY-B0388",
        400,
        29500,
        BatchStatus.quarantined,
        "Label says Ne 30/1, lab test reads Ne 28/1. Held for supplier response.",
    )
    batch(rc2, "SLY", ("Ne 30/1", "Navy"), "SLY-N0415", 500, 29500, BatchStatus.inspection)
    batch(
        rc2,
        "SLY",
        None,
        None,
        250,
        29500,
        BatchStatus.pending_identification,
        "No supplier label on 10 cones.",
    )
    batch(
        rc2,
        "SLY",
        ("Ne 40/1", "Black"),
        "SLY-B0390",
        300,
        31000,
        BatchStatus.rejected,
        "Shade far off approved standard.",
    )
    del rc3  # truck at the gate: draft receipt, no batches yet

    # --- reservations, one per status
    shirt_kg = Decimal("213.537")
    db.add_all(
        [
            Reservation(
                yarn_batch_id=yb_navy40.id,
                order_id=so_shirt.id,
                kg=shirt_kg,
                status=ReservationStatus.active,
            ),
            Reservation(
                yarn_batch_id=yb_white40.id,
                order_id=so_closed.id,
                kg=Decimal("40.04"),
                status=ReservationStatus.consumed,
            ),
            Reservation(
                yarn_batch_id=yb_white40.id,
                order_id=so_cancel.id,
                kg=Decimal("100"),
                status=ReservationStatus.released,
            ),
        ]
    )

    # --- work orders through the real service, then placed in every status
    for o in (so_closed, so_shirt, so_dyed, so_drill):
        create_work_orders(db, o.id, user[Role.sales].id)
    wo = {(w.order_id, w.stage): w for w in db.scalars(select(WorkOrder))}
    w_closed = wo[(so_closed.id, Stage.weaving)]
    w_closed.status, w_closed.machine_id = WorkOrderStatus.done, mc["LM-04"].id
    w_closed.started_at, w_closed.finished_at = NOW - timedelta(days=9), NOW - timedelta(days=7)
    w_shirt = wo[(so_shirt.id, Stage.weaving)]
    w_shirt.status, w_shirt.machine_id = WorkOrderStatus.running, mc["LM-01"].id
    w_shirt.started_at = NOW - timedelta(days=3)
    w_dyed_weave = wo[(so_dyed.id, Stage.weaving)]
    w_dyed_weave.status, w_dyed_weave.machine_id = WorkOrderStatus.done, mc["LM-02"].id
    w_dyed_weave.started_at, w_dyed_weave.finished_at = (
        NOW - timedelta(days=6),
        NOW - timedelta(days=1),
    )
    w_dye = wo[(so_dyed.id, Stage.dyeing)]
    w_dye.status, w_dye.machine_id, w_dye.queue_position = (
        WorkOrderStatus.queued,
        mc["DYE-01"].id,
        1,
    )
    w_spin = wo[(so_drill.id, Stage.spinning)]
    w_spin.status, w_spin.machine_id = WorkOrderStatus.paused, mc["SPN-01"].id
    w_spin.started_at = NOW - timedelta(days=2)
    # drill weaving stays waiting

    # --- machine events, every status
    for code, status, reason, w, hours in [
        ("LM-01", MachineStatus.running, None, w_shirt, 70),
        ("LM-02", MachineStatus.idle, "Job finished", None, 20),
        ("SPN-01", MachineStatus.running, None, w_spin, 48),
        ("SPN-01", MachineStatus.breakdown, "Spindle bearing failure", w_spin, 5),
        ("DYE-02", MachineStatus.maintenance, "Scheduled boiler service", None, 3),
        ("LM-06", MachineStatus.off, None, None, 24),
    ]:
        db.add(
            MachineEvent(
                machine_id=mc[code].id,
                at=NOW - timedelta(hours=hours),
                status=status,
                reason=reason,
                work_order_id=w.id if w else None,
                source=Source.machine if code.startswith("LM") else Source.manual,
                user_id=user[Role.supervisor].id,
            )
        )

    # --- crew and attendance for today's shift A
    a_start = datetime.combine(TODAY, time(0, 30), UTC)  # 06:00 IST
    for wcode, mcode in [("W-009", "LM-01"), ("W-010", "LM-02"), ("W-001", "SPN-01")]:
        db.add(
            CrewAssignment(
                date=TODAY,
                shift_id=shift["A"].id,
                worker_id=worker[wcode].id,
                machine_id=mc[mcode].id,
                from_at=a_start,
            )
        )
    for wcode, status, src in [
        ("W-009", AttendanceStatus.present, AttendanceSource.crew),
        ("W-010", AttendanceStatus.present, AttendanceSource.crew),
        ("W-001", AttendanceStatus.half_day, AttendanceSource.manual),
        ("W-002", AttendanceStatus.absent, AttendanceSource.manual),
    ]:
        db.add(
            Attendance(
                date=TODAY,
                shift_id=shift["A"].id,
                worker_id=worker[wcode].id,
                status=status,
                source=src,
            )
        )

    # --- yarn issued to looms and consumed (lineage source for rolls)
    for b, w, kg in [(yb_white40, w_closed, Decimal("40.04")), (yb_navy40, w_shirt, Decimal(120))]:
        at = w.started_at
        move(ItemKind.yarn, b.id, kg, "YS-01", "WIP", MoveReason.issue, at, ("work_order", w.id))
        move(
            ItemKind.yarn,
            b.id,
            kg,
            "WIP",
            "PROD",
            MoveReason.consume,
            at + timedelta(hours=8),
            ("work_order", w.id),
        )

    # --- rolls, every status
    def roll(o, w, loom, weaver, length, status, batch_row, kg, days_ago, band=None):
        made = NOW - timedelta(days=days_ago)
        passed = status in (RollStatus.passed, RollStatus.dispatched)
        where = {
            RollStatus.passed: "FG-01",
            RollStatus.rejected: "REJ",
            RollStatus.dispatched: "DISP",
        }.get(status, "WIP")
        r = Roll(
            code=next_code(db, "R"),
            order_id=o.id,
            work_order_id=w.id,
            loom_machine_id=mc[loom].id,
            shift_id=shift["A"].id,
            weaver_id=worker[weaver].id,
            length_m=Decimal(length),
            status=status,
            shade_band=band,
            location_id=loc[where].id,
            passed_at=made + timedelta(hours=6) if passed else None,
        )
        db.add(r)
        db.flush()
        db.add(RollBatch(roll_id=r.id, yarn_batch_id=batch_row.id, kg=qty(kg)))
        db.add(
            RollEvent(
                roll_id=r.id, at=made, kind="woven", machine_id=mc[loom].id, work_order_id=w.id
            )
        )
        db.add(
            ProductionLog(
                work_order_id=w.id,
                machine_id=mc[loom].id,
                shift_id=shift["A"].id,
                worker_id=worker[weaver].id,
                qty=Decimal(length),
                unit=Unit.m,
                at=made,
                source=Source.machine,
            )
        )
        move(
            ItemKind.fabric,
            r.id,
            length,
            "PROD",
            "WIP",
            MoveReason.produce,
            made,
            ("work_order", w.id),
            Source.machine,
        )
        return r

    def qc(r, decision, attempt, defects=(), band=None, hours=4):
        db.add(
            QcCheck(
                roll_id=r.id,
                inspector_id=user[Role.qc].id,
                attempt_no=attempt,
                at=NOW - timedelta(hours=hours),
                decision=decision,
                defects=[{"type": t, "count": n} for t, n in defects],
                shade_band=band,
                gsm=Decimal(116) if decision == QcDecision.pass_ else None,
                width_cm=Decimal(147) if decision == QcDecision.pass_ else None,
            )
        )

    roll(so_shirt, w_shirt, "LM-01", "W-009", 62, RollStatus.in_process, yb_navy40, 11, 0)
    roll(so_shirt, w_shirt, "LM-01", "W-009", 60, RollStatus.awaiting_qc, yb_navy40, 10.7, 1)
    r_pass = roll(
        so_shirt, w_shirt, "LM-01", "W-009", 61, RollStatus.passed, yb_navy40, 10.9, 2, band="A"
    )
    qc(r_pass, QcDecision.pass_, 1, band="A", hours=30)
    move(
        ItemKind.fabric,
        r_pass.id,
        61,
        "WIP",
        "FG-01",
        MoveReason.qc_pass,
        NOW - timedelta(hours=30),
    )
    r_rework = roll(so_shirt, w_shirt, "LM-01", "W-010", 59, RollStatus.rework, yb_navy40, 10.5, 2)
    qc(r_rework, QcDecision.rework, 1, defects=[("hole", 2)], hours=26)
    r_rej = roll(so_shirt, w_shirt, "LM-01", "W-010", 58, RollStatus.rejected, yb_navy40, 10.3, 3)
    qc(r_rej, QcDecision.reject, 1, defects=[("colour_mismatch", 1), ("uneven_weave", 3)], hours=50)
    move(
        ItemKind.fabric, r_rej.id, 58, "WIP", "REJ", MoveReason.qc_reject, NOW - timedelta(hours=50)
    )

    shipped = []
    for i in range(3):
        r = roll(
            so_closed,
            w_closed,
            "LM-04",
            "W-011",
            75,
            RollStatus.dispatched,
            yb_white40,
            Decimal("13.347"),
            8,
            band="A",
        )
        qc(r, QcDecision.pass_, 1, band="A", hours=7 * 24 + i)
        move(ItemKind.fabric, r.id, 75, "WIP", "FG-01", MoveReason.qc_pass, NOW - timedelta(days=7))
        shipped.append(r)

    # --- dispatches (every status) and invoices (every status) for the closed order
    def dispatch(o, status, vehicle=None, days_ago=0):
        d = Dispatch(
            code=next_code(db, "DN"),
            order_id=o.id,
            buyer_id=o.buyer_id,
            vehicle_no=vehicle,
            driver="Ravi" if vehicle else None,
            status=status,
            confirmed_at=NOW - timedelta(days=days_ago)
            if status == DispatchStatus.confirmed
            else None,
        )
        db.add(d)
        db.flush()
        return d

    for i, (r, inv_status) in enumerate(
        zip(
            shipped,
            [InvoiceStatus.paid, InvoiceStatus.part_paid, InvoiceStatus.issued],
            strict=True,
        )
    ):
        days_ago = 6 - i
        d = dispatch(so_closed, DispatchStatus.confirmed, f"KA-01-AB-12{i}4", days_ago)
        db.add(DispatchRoll(dispatch_id=d.id, roll_id=r.id))
        move(
            ItemKind.fabric,
            r.id,
            75,
            "FG-01",
            "DISP",
            MoveReason.dispatch,
            d.confirmed_at,
            ("dispatch", d.id),
        )
        amount = line_amount_paise(so_closed.rate_paise_per_m, r.length_m)
        tax = amount * 5 // 100  # GST 5% on cotton fabric (HSN 5208)
        inv = Invoice(
            code=next_code(db, "INV"),
            dispatch_id=d.id,
            buyer_id=so_closed.buyer_id,
            order_id=so_closed.id,
            subtotal_paise=amount,
            tax_paise=tax,
            total_paise=amount + tax,
            issued_at=d.confirmed_at,
            due_date=d.confirmed_at.date() + timedelta(days=30),
            status=inv_status,
        )
        db.add(inv)
        db.flush()
        db.add(
            InvoiceLine(
                invoice_id=inv.id,
                roll_id=r.id,
                metres=r.length_m,
                rate_paise_per_m=so_closed.rate_paise_per_m,
                amount_paise=amount,
            )
        )
        paid = {
            InvoiceStatus.paid: inv.total_paise,
            InvoiceStatus.part_paid: inv.total_paise // 2,
        }.get(inv_status)
        if paid:
            db.add(
                Payment(
                    invoice_id=inv.id,
                    amount_paise=paid,
                    mode=PaymentMode.bank_transfer,
                    received_at=NOW - timedelta(days=1),
                    ref=f"NEFT{inv.id:08d}",
                )
            )

    draft = dispatch(so_shirt, DispatchStatus.draft)
    db.add(DispatchRoll(dispatch_id=draft.id, roll_id=r_pass.id))
    dispatch(so_shirt, DispatchStatus.loading, "KA-51-C-7781")

    # --- wage runs (every status), expenses, insights
    month_start = TODAY.replace(day=1)
    for months_back, status in [
        (2, WageRunStatus.paid),
        (1, WageRunStatus.final),
        (0, WageRunStatus.draft),
    ]:
        start = month_start
        for _ in range(months_back):
            start = (start - timedelta(days=1)).replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        run = WageRun(period_start=start, period_end=end, status=status)
        db.add(run)
        db.flush()
        db.add(
            WageLine(
                wage_run_id=run.id,
                worker_id=worker["W-001"].id,
                days=Decimal(26),
                metres=Decimal(0),
                amount_paise=26 * 65000,
            )
        )
        db.add(
            WageLine(
                wage_run_id=run.id,
                worker_id=worker["W-009"].id,
                days=Decimal(25),
                metres=Decimal(3900),
                amount_paise=3900 * 400,
            )
        )

    for cat, amount, note in [
        (ExpenseCategory.power, 18_500_000, "BESCOM bill"),
        (ExpenseCategory.maintenance, 2_450_000, "SPN-01 bearings"),
    ]:
        db.add(
            Expense(date=TODAY - timedelta(days=2), category=cat, amount_paise=amount, note=note)
        )

    for kind, sev, etype, eid, title, facts, status in [
        (
            "machine_downtime",
            Severity.critical,
            "machine",
            mc["SPN-01"].id,
            "SPN-01 down 5 h: spindle bearing failure",
            {"hours_down": 5},
            InsightStatus.open,
        ),
        (
            "supplier_quality",
            Severity.warn,
            "supplier",
            sup["SLY"].id,
            "2 of 5 Sri Lakshmi batches failed inspection this month",
            {"failed": 2, "received": 5},
            InsightStatus.acknowledged,
        ),
        (
            "low_stock",
            Severity.info,
            "yarn_item",
            yarn[("Ne 30/1", "Black")].id,
            "Cotton Ne 30/1 Black below reorder level",
            {"free_kg": 0, "reorder_kg": 250},
            InsightStatus.resolved,
        ),
    ]:
        db.add(
            Insight(
                kind=kind,
                severity=sev,
                entity_type=etype,
                entity_id=eid,
                title=title,
                facts=facts,
                status=status,
            )
        )


def main() -> None:
    with SessionLocal() as db:
        seed_masters(db)
        if db.scalar(select(Order.id).limit(1)):
            print("masters checked; demo data already present, skipped")
        else:
            seed_demo(db)
            print("seeded masters and demo data")
        db.commit()
    print(f"logins: <role>@everest.local / {DEMO_PASSWORD}  roles: {', '.join(Role)}")


if __name__ == "__main__":
    main()
