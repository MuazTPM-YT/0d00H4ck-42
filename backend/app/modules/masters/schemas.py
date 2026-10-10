from datetime import time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from app.core.enums import Stage, Unit
from app.core.errors import FieldError
from app.core.types import Code, Gstin, Name, NonNegativeQty, Paise, Phone, PositiveQty, ShortText
from app.modules.masters.models import LocationKind, WageType

Pct = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]


# outputs use plain types: input rules must never turn stored data into a 500
class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- suppliers
class SupplierIn(BaseModel):
    code: Code
    name: Name
    gstin: Gstin | None = None
    phone: Phone | None = None
    city: Name | None = None
    active: bool = True


class SupplierOut(Out):
    code: str
    name: str
    gstin: str | None
    phone: str | None
    city: str | None
    active: bool


# --- buyers
class BuyerIn(BaseModel):
    code: Code
    name: Name
    gstin: Gstin
    contact_name: Name | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    city: Name | None = None
    active: bool = True


class BuyerOut(Out):
    code: str
    name: str
    gstin: str
    contact_name: str | None
    phone: str | None
    email: str | None
    city: str | None
    active: bool


# --- yarn items
class YarnItemIn(BaseModel):
    fibre: ShortText
    count: Annotated[str, Field(min_length=1, max_length=20, pattern=r"^\S(.*\S)?$")]
    colour: ShortText
    reorder_level_kg: NonNegativeQty = Decimal(0)
    active: bool = True


class YarnItemOut(Out):
    fibre: str
    count: str
    colour: str
    reorder_level_kg: Decimal
    active: bool


# --- fabric types (route stages + yarn recipe travel with the fabric)
class StageIn(BaseModel):
    seq: Annotated[int, Field(gt=0, le=20)]
    stage: Stage


class RecipeIn(BaseModel):
    fibre: ShortText
    count: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    share_pct: Pct


class FabricTypeIn(BaseModel):
    code: Code
    name: Name
    width_cm: Annotated[Decimal, Field(gt=0, le=1000, max_digits=7, decimal_places=2)]
    gsm: Annotated[Decimal, Field(gt=0, le=2000, max_digits=7, decimal_places=2)]
    process_loss_pct: Annotated[Decimal, Field(ge=0, lt=100, max_digits=5, decimal_places=2)]
    active: bool = True
    stages: Annotated[list[StageIn], Field(min_length=1, max_length=5)]
    recipe: Annotated[list[RecipeIn], Field(min_length=1, max_length=10)]

    # rolls are born at weaving, so every route weaves; recipe must cover 100% of the fabric
    @model_validator(mode="after")
    def check_route_and_recipe(self):
        seqs = [s.seq for s in self.stages]
        stages = [s.stage for s in self.stages]
        if len(set(seqs)) != len(seqs):
            raise FieldError("stages", "Stage sequence numbers must be unique")
        if len(set(stages)) != len(stages):
            raise FieldError("stages", "A stage can appear only once in the route")
        if Stage.weaving not in stages:
            raise FieldError("stages", "Route must include weaving")
        keys = [(r.fibre.lower(), r.count.lower()) for r in self.recipe]
        if len(set(keys)) != len(keys):
            raise FieldError("recipe", "Recipe lists the same yarn twice")
        if sum(r.share_pct for r in self.recipe) != 100:
            raise FieldError("recipe", "Recipe shares must add up to 100%")
        return self


class StageOut(Out):
    seq: int
    stage: Stage


class RecipeOut(Out):
    fibre: str
    count: str
    share_pct: Decimal


class FabricTypeOut(Out):
    code: str
    name: str
    width_cm: Decimal
    gsm: Decimal
    process_loss_pct: Decimal
    active: bool
    stages: list[StageOut]
    recipe: list[RecipeOut]


# --- machines
class MachineIn(BaseModel):
    code: Code
    name: Name
    type: Stage
    hourly_cost_paise: Paise
    rated_output_per_hour: PositiveQty
    output_unit: Unit
    active: bool = True

    # spinning makes yarn (kg); weaving and dyeing handle fabric (m)
    @model_validator(mode="after")
    def unit_fits_type(self):
        expected = Unit.kg if self.type == Stage.spinning else Unit.m
        if self.output_unit != expected:
            raise FieldError("output_unit", f"{self.type} machines report output in {expected}")
        return self


class MachineOut(Out):
    code: str
    name: str
    type: Stage
    hourly_cost_paise: int
    rated_output_per_hour: Decimal
    output_unit: Unit
    active: bool


# --- workers
class WorkerIn(BaseModel):
    code: Code
    name: Name
    wage_type: WageType
    daily_rate_paise: Annotated[int, Field(gt=0, le=10**8)] | None = None
    piece_rate_paise_per_m: Annotated[int, Field(gt=0, le=10**7)] | None = None
    active: bool = True

    @model_validator(mode="after")
    def rate_fits_wage_type(self):
        if self.wage_type == WageType.daily and not self.daily_rate_paise:
            raise FieldError("daily_rate_paise", "Daily-wage worker needs a daily rate")
        if self.wage_type == WageType.piece and not self.piece_rate_paise_per_m:
            raise FieldError("piece_rate_paise_per_m", "Piece-rate worker needs a rate per metre")
        return self


class WorkerOut(Out):
    code: str
    name: str
    wage_type: WageType
    daily_rate_paise: int | None
    piece_rate_paise_per_m: int | None
    active: bool


# --- shifts
class ShiftIn(BaseModel):
    code: Annotated[str, Field(pattern=r"^[A-Z]$")]
    name: ShortText
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def has_length(self):
        if self.start_time == self.end_time:
            raise FieldError("end_time", "Shift start and end cannot be the same time")
        return self


class ShiftOut(Out):
    code: str
    name: str
    start_time: time
    end_time: time


class LocationOut(Out):
    code: str
    name: str
    kind: LocationKind
