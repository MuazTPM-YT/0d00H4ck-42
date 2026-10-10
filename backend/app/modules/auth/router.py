from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import COOKIE_NAME, get_current_user
from app.core.security import create_token
from app.modules.auth import service
from app.modules.auth.models import User
from app.modules.auth.schemas import LoginIn, LoginOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


# token in httpOnly cookie for the browser, and in the body for scanners and machine feeds
@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = service.authenticate(db, body.email, body.password)
    token = create_token(user.id, user.role)
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        max_age=s.jwt_expire_minutes * 60,
        path="/",
    )
    return {"user": user, "access_token": token}


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
