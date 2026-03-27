from __future__ import annotations

# GRACE[M-AUTH][SECURITY][BLOCK_AdminSession]
# CONTRACT: bcrypt; login_user; require_admin / session_admin_user для UI и API.

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.db import get_db
from app.models import AdminUser
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def login_user(db: Session, username: str, password: str) -> AdminUser | None:
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def require_admin(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AdminUser:
    uid = request.session.get("admin_user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Требуется вход")
    user = db.get(AdminUser, int(uid))
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    return user


def redirect_if_not_authenticated(request: Request, path: str = "/login") -> RedirectResponse | None:
    if not request.session.get("admin_user_id"):
        return RedirectResponse(url=path, status_code=302)
    return None


def session_admin_user(request: Request, db: Session) -> AdminUser | None:
    uid = request.session.get("admin_user_id")
    if not uid:
        return None
    return db.get(AdminUser, int(uid))


def has_any_admin(db: Session) -> bool:
    return db.scalar(select(AdminUser).limit(1)) is not None
