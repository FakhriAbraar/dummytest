"""Login auth untuk halaman admin (JWT bearer + bcrypt).

POST /api/pad/auth/login  → {access_token, user}
GET  /api/pad/auth/me     → profil user dari token (proteksi via Authorization: Bearer)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sql import get_db_session
from app.db.tables import SystemUser
from app.services import auth as auth_svc

router = APIRouter(prefix="/auth", tags=["Auth"])

DB = Annotated[AsyncSession, Depends(get_db_session)]
_bearer = HTTPBearer(auto_error=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    user_id: int
    email: str | None = None
    full_name: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, session: DB) -> LoginResponse:
    email = payload.email.strip().lower()
    user = (
        await session.execute(select(SystemUser).where(SystemUser.email == email))
    ).scalars().first()
    if (
        user is None
        or not user.is_active
        or not auth_svc.verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email atau kata sandi salah.",
        )
    token = auth_svc.create_access_token(user_id=user.user_id, email=user.email or "")
    return LoginResponse(
        access_token=token,
        user=UserOut(user_id=user.user_id, email=user.email, full_name=user.full_name),
    )


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    session: DB,
) -> SystemUser:
    """Dependency untuk endpoint yang perlu proteksi token (mis. /me)."""
    try:
        data = auth_svc.decode_token(creds.credentials)
        user_id = int(data.get("sub", 0))
    except Exception as exc:  # token kadaluarsa / signature salah / malformed
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid atau kadaluarsa.",
        ) from exc

    user = await session.get(SystemUser, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun tidak ditemukan atau nonaktif.",
        )
    return user


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[SystemUser, Depends(get_current_user)]) -> UserOut:
    return UserOut(user_id=user.user_id, email=user.email, full_name=user.full_name)
