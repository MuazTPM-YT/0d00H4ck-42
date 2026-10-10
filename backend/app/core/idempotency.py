from collections.abc import Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base
from app.core.errors import Conflict


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    scope: Mapped[str] = mapped_column(String(60))
    response: Mapped[dict] = mapped_column(JSONB)


# repeat of same key returns first response; fn must not commit, caller commits once
def run_once(db: Session, key: str | None, scope: str, fn: Callable[[], object]) -> dict:
    if not key:
        return jsonable_encoder(fn())
    saved = db.scalar(select(IdempotencyKey).where(IdempotencyKey.key == key))
    if saved:
        if saved.scope != scope:
            raise Conflict(
                "Idempotency key already used for another action", field="idempotency_key"
            )
        return saved.response
    response = jsonable_encoder(fn())
    db.add(IdempotencyKey(key=key, scope=scope, response=response))
    db.flush()
    return response
