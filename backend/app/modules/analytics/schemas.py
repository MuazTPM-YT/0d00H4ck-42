from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.analytics.models import InsightStatus, Severity


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    severity: Severity
    entity_type: str
    entity_id: int
    title: str
    facts: dict
    narrative: str | None
    status: InsightStatus
    created_at: datetime
