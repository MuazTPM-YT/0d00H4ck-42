from collections.abc import Mapping
from enum import StrEnum

from app.core.errors import Conflict

TransitionMap = Mapping[StrEnum, set[StrEnum]]


# every status change goes through here; anything off the map is 409
def check_transition(transitions: TransitionMap, current: StrEnum, new: StrEnum) -> None:
    if new not in transitions.get(current, set()):
        raise Conflict(
            f"Cannot change status from '{current}' to '{new}'",
            field="status",
            code="illegal_transition",
        )
