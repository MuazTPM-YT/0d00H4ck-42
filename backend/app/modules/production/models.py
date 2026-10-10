from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import Source, Stage, Unit, str_enum


class WorkOrderStatus(StrEnum):
    waiting = "waiting"
    queued = "queued"
    running = "running"
    paused = "paused"
    done = "done"


class MachineStatus(StrEnum):
    running = "running"
    idle = "idle"
    breakdown = "breakdown"
    maintenance = "maintenance"
    off = "off"


# one stage of one order; roll_id set only on rework work orders
class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint("planned_qty > 0", name="planned_qty_positive"),
        CheckConstraint("seq > 0", name="seq_positive"),
        CheckConstraint(
            "status <> 'running' OR machine_id IS NOT NULL", name="running_has_machine"
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finish_after_start",
        ),
        Index(
            "uq_work_orders_one_running_per_machine",
            "machine_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index(
            "uq_work_orders_order_seq",
            "order_id",
            "seq",
            unique=True,
            postgresql_where=text("roll_id IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    stage: Mapped[Stage] = mapped_column(str_enum(Stage, "stage"))
    seq: Mapped[int] = mapped_column(Integer)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id"), index=True)
    planned_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[Unit] = mapped_column(str_enum(Unit, "unit"))
    status: Mapped[WorkOrderStatus] = mapped_column(
        str_enum(WorkOrderStatus, "work_order_status"), default=WorkOrderStatus.waiting
    )
    queue_position: Mapped[int | None] = mapped_column(Integer)
    # use_alter: rolls and work_orders point at each other
    roll_id: Mapped[int | None] = mapped_column(ForeignKey("rolls.id", use_alter=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# append-only machine status history; current status = latest row per machine
class MachineEvent(Base):
    __tablename__ = "machine_events"
    __table_args__ = (
        CheckConstraint(
            "status NOT IN ('breakdown', 'maintenance') OR reason IS NOT NULL",
            name="downtime_has_reason",
        ),
        Index("ix_machine_events_machine_at", "machine_id", "at"),
    )

    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[MachineStatus] = mapped_column(str_enum(MachineStatus, "machine_status"))
    reason: Mapped[str | None] = mapped_column(Text)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), index=True)
    source: Mapped[Source] = mapped_column(str_enum(Source, "source"), default=Source.manual)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)


class ProductionLog(Base):
    __tablename__ = "production_logs"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), index=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[Unit] = mapped_column(str_enum(Unit, "unit"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[Source] = mapped_column(str_enum(Source, "source"), default=Source.manual)
