from datetime import time
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import Stage, Unit, str_enum


class LocationKind(StrEnum):
    inspection = "inspection"
    quarantine = "quarantine"
    store = "store"
    wip = "wip"
    finished = "finished"
    rejected = "rejected"
    dispatched = "dispatched"
    supplier = "supplier"
    consumed = "consumed"


class WageType(StrEnum):
    daily = "daily"
    piece = "piece"


class Supplier(Base):
    __tablename__ = "suppliers"

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Buyer(Base):
    __tablename__ = "buyers"

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    gstin: Mapped[str] = mapped_column(String(15), unique=True)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    city: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class YarnItem(Base):
    __tablename__ = "yarn_items"
    __table_args__ = (
        UniqueConstraint("fibre", "count", "colour"),
        CheckConstraint("reorder_level_kg >= 0", name="reorder_level_non_negative"),
    )

    fibre: Mapped[str] = mapped_column(String(60))
    count: Mapped[str] = mapped_column(String(20))
    colour: Mapped[str] = mapped_column(String(40))
    reorder_level_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class FabricType(Base):
    __tablename__ = "fabric_types"
    __table_args__ = (
        CheckConstraint("width_cm > 0", name="width_positive"),
        CheckConstraint("gsm > 0", name="gsm_positive"),
        CheckConstraint("process_loss_pct >= 0 AND process_loss_pct < 100", name="loss_range"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    width_cm: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    gsm: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    process_loss_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    stages: Mapped[list["FabricTypeStage"]] = relationship(
        order_by="FabricTypeStage.seq", cascade="all, delete-orphan", lazy="selectin"
    )
    recipe: Mapped[list["FabricRecipe"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class FabricTypeStage(Base):
    __tablename__ = "fabric_type_stages"
    __table_args__ = (
        UniqueConstraint("fabric_type_id", "seq"),
        UniqueConstraint("fabric_type_id", "stage"),
        CheckConstraint("seq > 0", name="seq_positive"),
    )

    fabric_type_id: Mapped[int] = mapped_column(ForeignKey("fabric_types.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    stage: Mapped[Stage] = mapped_column(str_enum(Stage, "stage"))


# share of each yarn in the fabric; shares per fabric sum to 100 (checked in service)
class FabricRecipe(Base):
    __tablename__ = "fabric_recipe"
    __table_args__ = (
        UniqueConstraint("fabric_type_id", "fibre", "count"),
        CheckConstraint("share_pct > 0 AND share_pct <= 100", name="share_range"),
    )

    fabric_type_id: Mapped[int] = mapped_column(
        ForeignKey("fabric_types.id", ondelete="CASCADE"), index=True
    )
    fibre: Mapped[str] = mapped_column(String(60))
    count: Mapped[str] = mapped_column(String(20))
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))


class Machine(Base):
    __tablename__ = "machines"
    __table_args__ = (
        CheckConstraint("hourly_cost_paise >= 0", name="cost_non_negative"),
        CheckConstraint("rated_output_per_hour > 0", name="rated_output_positive"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[Stage] = mapped_column(str_enum(Stage, "machine_type"))
    hourly_cost_paise: Mapped[int] = mapped_column(BigInteger)
    rated_output_per_hour: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    output_unit: Mapped[Unit] = mapped_column(str_enum(Unit, "output_unit"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint(
            "(wage_type = 'daily' AND daily_rate_paise > 0)"
            " OR (wage_type = 'piece' AND piece_rate_paise_per_m > 0)",
            name="rate_matches_wage_type",
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    wage_type: Mapped[WageType] = mapped_column(str_enum(WageType, "wage_type"))
    daily_rate_paise: Mapped[int | None] = mapped_column(BigInteger)
    piece_rate_paise_per_m: Mapped[int | None] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


# night shift crosses midnight, so end may be before start
class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (CheckConstraint("start_time <> end_time", name="non_zero_length"),)

    code: Mapped[str] = mapped_column(String(5), unique=True)
    name: Mapped[str] = mapped_column(String(40))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class Location(Base):
    __tablename__ = "locations"

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[LocationKind] = mapped_column(str_enum(LocationKind, "location_kind"))
