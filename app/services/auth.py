"""Auth helpers: password hashing (bcrypt) + JWT issuing/decoding.

Dipakai oleh router ``app.api.pad.auth`` untuk login admin. Akun admin default
dipastikan ada saat startup lewat :func:`ensure_default_admin` (dipanggil dari
lifespan), sehingga sistem selalu punya minimal satu kredensial login.
"""

from __future__ import annotations

import datetime as dt

import bcrypt
import jwt

from app.settings import settings

_ALGO = "HS256"
# Panjang hash bcrypt yang valid selalu 60 char — dipakai untuk mendeteksi hash
# dummy dari seed lama (mis. "$2b$12$dummy_hash_admin") yang tidak bisa diverifikasi.
_BCRYPT_LEN = 60


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed or len(hashed) != _BCRYPT_LEN:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: int, email: str) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGO])


async def ensure_default_admin() -> None:
    """Pastikan akun admin default ada & bisa login.

    Dipanggil dari lifespan setelah ``create_all``. Jika belum ada, dibuat. Jika
    ada tapi password_hash-nya tidak valid (mis. hash dummy dari seed), di-reset
    ke password default agar login admin selalu berfungsi.
    """
    from sqlalchemy import select

    from app.db.sql import get_session_factory
    from app.db.tables import SystemUser

    factory = get_session_factory()
    email = settings.admin_email.strip().lower()
    async with factory() as session:
        user = (
            await session.execute(select(SystemUser).where(SystemUser.email == email))
        ).scalars().first()
        if user is None:
            session.add(
                SystemUser(
                    full_name=settings.admin_full_name,
                    email=email,
                    password_hash=hash_password(settings.admin_password),
                    registered_at=dt.datetime.now(tz=dt.timezone.utc),
                    is_active=True,
                )
            )
            await session.commit()
            print(f"[auth] Akun admin default dibuat: {email}")  # noqa: T201
        elif not verify_password(settings.admin_password, user.password_hash) and (
            not user.password_hash or len(user.password_hash) != _BCRYPT_LEN
        ):
            # Hash lama tidak valid (dummy) → reset agar admin tetap bisa masuk.
            user.password_hash = hash_password(settings.admin_password)
            user.is_active = True
            await session.commit()
            print(f"[auth] Password admin di-reset ke default untuk: {email}")  # noqa: T201
