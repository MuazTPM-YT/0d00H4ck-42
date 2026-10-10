from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class RollStatus(StrEnum):
    in_process = "in_process"
    awaiting_qc = "awaiting_qc"
    passed = "passed"
    rework = "rework"
    rejected = "rejected"
    dispatched = "dispatched"


class QcDecision(StrEnum):
    pass_ = "pass"
    rework = "rework"
    reject = "reject"


# weaving and dyeing faults an inspector marks on the table; stored in qc_checks.defects
class DefectType(StrEnum):
    hole = "hole"
    colour_mismatch = "colour_mismatch"
    uneven_weave = "uneven_weave"
    broken_end = "broken_end"
    broken_pick = "broken_pick"
    stain = "stain"
    selvedge = "selvedge"
    other = "other"


SHADE_BANDS = ("A", "B", "C")


# fabric roll, born at weaving; every roll keeps order, loom, shift, weaver
class Roll(Base):
    __tablename__ = "rolls"
    __table_args__ = (
        CheckConstraint("length_m > 0", name="length_positive"),
        CheckConstraint("shade_band IS NULL OR shade_band IN ('A', 'B', 'C')", name="shade_band"),
        CheckConstraint(
            "status NOT IN ('passed', 'dispatched') OR passed_at IS NOT NULL",
            name="passed_has_time",
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), index=True)
    loom_machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    weaver_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), index=True)
    length_m: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    status: Mapped[RollStatus] = mapped_column(
        str_enum(RollStatus, "roll_status"), default=RollStatus.in_process
    )
    shade_band: Mapped[str | None] = mapped_column(String(1))
    dye_lot: Mapped[str | None] = mapped_column(String(40))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# lineage: which yarn batches went into which roll
class RollBatch(Base):
    __tablename__ = "roll_batches"
    __table_args__ = (
        UniqueConstraint("roll_id", "yarn_batch_id"),
        CheckConstraint("kg > 0", name="kg_positive"),
    )

    roll_id: Mapped[int] = mapped_column(ForeignKey("rolls.id"))
    yarn_batch_id: Mapped[int] = mapped_column(ForeignKey("yarn_batches.id"), index=True)
    kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))


class RollEvent(Base):
    __tablename__ = "roll_events"

    roll_id: Mapped[int] = mapped_column(ForeignKey("rolls.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(String(40))
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id"), index=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)


# one row per inspection attempt; defects = [{"type": "hole", "count": 2}]
class QcCheck(Base):
    __tablename__ = "qc_checks"
    __table_args__ = (
        UniqueConstraint("roll_id", "attempt_no"),
        CheckConstraint("attempt_no > 0", name="attempt_positive"),
        CheckConstraint("shade_band IS NULL OR shade_band IN ('A', 'B', 'C')", name="shade_band"),
        CheckConstraint("decision <> 'pass' OR shade_band IS NOT NULL", name="pass_has_shade"),
        CheckConstraint("gsm IS NULL OR gsm > 0", name="gsm_positive"),
        CheckConstraint("width_cm IS NULL OR width_cm > 0", name="width_positive"),
    )

    roll_id: Mapped[int] = mapped_column(ForeignKey("rolls.id"))
    inspector_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempt_no: Mapped[int] = mapped_column(Integer)
    decision: Mapped[QcDecision] = mapped_column(str_enum(QcDecision, "qc_decision"))
    defects: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    shade_band: Mapped[str | None] = mapped_column(String(1))
    gsm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    notes: Mapped[str | None] = mapped_column(Text)
