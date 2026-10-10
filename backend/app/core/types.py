from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

# shared input types: strip whitespace, so "   " is rejected as empty.
# patterns run before to_upper, hence (?i)
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
CODE_RE = r"(?i)^[A-Z0-9][A-Z0-9-]{0,19}$"
GSTIN_RE = r"(?i)^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
Code = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=CODE_RE)]
Gstin = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=GSTIN_RE)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9][0-9 -]{6,18}$")]
Paise = Annotated[int, Field(ge=0, le=10**14)]
PositiveQty = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
NonNegativeQty = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]
