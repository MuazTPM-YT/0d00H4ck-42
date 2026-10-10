from sqlalchemy import BigInteger, String, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base

PREFIXES = {"YB", "RC", "SO", "WO", "R", "DN", "INV"}


class CodeSequence(Base):
    __tablename__ = "code_sequences"

    prefix: Mapped[str] = mapped_column(String(10), unique=True)
    last_value: Mapped[int] = mapped_column(BigInteger, default=0)


# row-locked upsert in the caller's transaction: no duplicates, rollback leaves no gap
def next_code(db: Session, prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown code prefix {prefix}")
    value = db.execute(
        text(
            "INSERT INTO code_sequences (prefix, last_value) VALUES (:p, 1) "
            "ON CONFLICT (prefix) DO UPDATE SET last_value = code_sequences.last_value + 1 "
            "RETURNING last_value"
        ),
        {"p": prefix},
    ).scalar_one()
    return f"{prefix}-{value:06d}"
