from enum import StrEnum

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class Role(StrEnum):
    owner = "owner"
    store = "store"
    supervisor = "supervisor"
    qc = "qc"
    dispatch = "dispatch"
    accounts = "accounts"
    sales = "sales"


class User(Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
