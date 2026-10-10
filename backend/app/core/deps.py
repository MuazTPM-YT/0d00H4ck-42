from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.modules.auth.models import Role, User

COOKIE_NAME = "access_token"
bearer = HTTPBearer(auto_error=False)


# bearer header first (swagger, tests, scanners, machine feeds), then browser cookie
def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = creds.credentials if creds else request.cookies.get(COOKIE_NAME)
    user_id = decode_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if not user or not user.active:
        raise Unauthorized("Login required")
    return user


# same login check for a live stream, but its session closes before streaming starts: a tab
# open for hours must not pin a pooled connection idle in a transaction
def stream_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db, scope="function"),
) -> User:
    return get_current_user(request, creds, db)


# owner is admin and passes every role check
def require_roles(*roles: Role) -> Callable[..., User]:
    def check(user: User = Depends(get_current_user)) -> User:
        if user.role != Role.owner and user.role not in roles:
            raise Forbidden(f"Role '{user.role}' cannot do this")
        return user

    return check


MONEY_ROLES = (Role.owner, Role.accounts)


# rates and costs leave the server only for the desks that price and pay; others get the row
# with those fields blanked (the store still sees yarn cost: it types the rate at the gate)
def hide_money(out: type[BaseModel], rows: list, user: User, fields: tuple[str, ...]) -> list:
    if not fields or user.role in MONEY_ROLES:
        return rows
    blank = dict.fromkeys(fields)
    return [out.model_validate(r, from_attributes=True).model_copy(update=blank) for r in rows]
