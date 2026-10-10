from enum import StrEnum

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class Severity(StrEnum):
    info = "info"
    warn = "warn"
    critical = "critical"


class InsightStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


# computed finding; facts hold the numbers, narrative only phrases them
class Insight(Base):
    __tablename__ = "insights"
    __table_args__ = (Index("ix_insights_entity", "entity_type", "entity_id"),)

    kind: Mapped[str] = mapped_column(String(60))
    severity: Mapped[Severity] = mapped_column(str_enum(Severity, "severity"))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(200))
    facts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    narrative: Mapped[str | None] = mapped_column(Text)
    status: Mapped[InsightStatus] = mapped_column(
        str_enum(InsightStatus, "insight_status"), default=InsightStatus.open
    )
