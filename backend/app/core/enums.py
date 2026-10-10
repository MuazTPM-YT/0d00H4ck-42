from enum import StrEnum

from sqlalchemy import Enum


class Stage(StrEnum):
    spinning = "spinning"
    weaving = "weaving"
    dyeing = "dyeing"


class Unit(StrEnum):
    kg = "kg"
    m = "m"


# where an event came from: tablet tap, barcode scanner, or machine feed
class Source(StrEnum):
    manual = "manual"
    scanner = "scanner"
    machine = "machine"


# VARCHAR + CHECK, not a native PG enum, so adding a value later is a plain migration
def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(m.value) for m in enum_cls),
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
