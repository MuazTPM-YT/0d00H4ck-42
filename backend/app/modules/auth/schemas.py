from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.modules.auth.models import Role

# plain string, not EmailStr: demo logins use the reserved .local domain
LoginEmail = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+$",
    ),
]


class LoginIn(BaseModel):
    email: LoginEmail
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role
    active: bool


class LoginOut(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"
