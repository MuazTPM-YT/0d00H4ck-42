from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Unauthorized
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User

# hash compared when the email is unknown, so timing does not reveal which emails exist
_DUMMY_HASH = hash_password("timing-guard")


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.active:
        raise Unauthorized("Wrong email or password", field="password")
    return user
