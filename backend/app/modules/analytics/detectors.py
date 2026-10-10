from datetime import datetime

from sqlalchemy.orm import Session

# Detector layer. Each detector reads the ledger and event tables (never writes them) and
# returns findings: {kind, severity, entity_type, entity_id, title, facts}. Facts carry the
# numbers shown to people and `records` (type, id, code) behind those numbers.
# Statistics learn each mill's own baseline from its own rows; nothing is pretrained.

DETECTORS = []


def find_all(db: Session, now: datetime) -> list[dict]:
    return [finding for detect in DETECTORS for finding in detect(db, now)]
