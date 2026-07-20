"""Аутентификация экранного клиента отдельным токеном устройства.

Код привязки предназначен только для первого подключения. После успешной
активации сервер выдаёт случайный screen token один раз и хранит в базе только
его SHA-256 хеш. Все дальнейшие REST-запросы экрана используют заголовок
``X-Screen-Token``. WebSocket передаёт тот же токен в первом register-сообщении,
потому что браузерный WebSocket API не позволяет установить произвольный
Authorization header.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from backend.config import config
from backend.database import get_db
from backend.models import Screen


SCREEN_TOKEN_HEADER = "X-Screen-Token"
_screen_token_header = APIKeyHeader(
    name=SCREEN_TOKEN_HEADER,
    auto_error=False,
    description="Постоянный токен конкретного экранного клиента",
)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_screen_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_pairing_code() -> str:
    upper_bound = 10 ** config.SCREEN_PAIRING_CODE_LENGTH
    value = secrets.randbelow(upper_bound)
    return f"{value:0{config.SCREEN_PAIRING_CODE_LENGTH}d}"


def pairing_expiry_from_now() -> datetime:
    return utc_now_naive() + timedelta(
        minutes=config.SCREEN_PAIRING_TTL_MINUTES
    )


def get_screen_by_token(db: Session, raw_token: str | None) -> Screen | None:
    if not raw_token:
        return None
    if len(raw_token) > 512:
        return None

    token_hash = hash_screen_token(raw_token)
    return (
        db.query(Screen)
        .filter(Screen.device_token_hash == token_hash)
        .one_or_none()
    )


def issue_screen_token(db: Session, screen: Screen) -> str:
    """Одноразово обменивает действующий pairing code на device token."""
    now = utc_now_naive()

    if not screen.is_connected:
        raise ValueError("screen is disabled")
    if screen.device_token_hash:
        raise ValueError("screen is already paired")
    if screen.pairing_expires_at is None or screen.pairing_expires_at < now:
        raise ValueError("pairing code is expired")

    for _ in range(10):
        raw_token = secrets.token_urlsafe(config.SCREEN_TOKEN_BYTES)
        token_hash = hash_screen_token(raw_token)
        collision = (
            db.query(Screen.id)
            .filter(Screen.device_token_hash == token_hash)
            .first()
        )
        if collision is None:
            break
    else:
        raise RuntimeError("Failed to generate a unique screen token")

    screen.device_token_hash = token_hash
    screen.token_created_at = now
    screen.activated_at = now
    screen.pairing_expires_at = None
    screen.is_online = True
    screen.last_active = now
    db.commit()
    db.refresh(screen)
    return raw_token


def rotate_screen_credentials(db: Session, screen: Screen) -> str:
    """Аннулирует старый device token и выдаёт новый короткоживущий код."""
    existing_codes = {
        row[0]
        for row in db.query(Screen.code)
        .filter(Screen.id != screen.id)
        .all()
    }

    for _ in range(500):
        code = generate_pairing_code()
        if code not in existing_codes:
            break
    else:
        raise RuntimeError("Failed to generate a unique pairing code")

    screen.code = code
    screen.device_token_hash = None
    screen.token_created_at = None
    screen.activated_at = None
    screen.pairing_expires_at = pairing_expiry_from_now()
    screen.is_online = False
    db.commit()
    db.refresh(screen)
    return code


def require_screen(
    raw_token: str | None = Depends(_screen_token_header),
    db: Session = Depends(get_db),
) -> Screen:
    """Dependency для REST API, доступного только привязанному экрану.

    Временная приостановка и отзыв учётных данных — разные состояния:
    * 423 ``screen_suspended``: токен правильный, но показ временно запрещён;
    * 401 ``screen_credentials_invalid``: токен отсутствует, неверен или отозван.
    """
    screen = get_screen_by_token(db, raw_token)

    if screen is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "ok": False,
                "error": "screen_credentials_invalid",
                "message": "Токен экрана недействителен или был отозван",
            },
        )

    if not screen.is_connected:
        # 423 Locked: сервер узнал устройство, но HR/admin временно запретил показ.
        # Device token здесь намеренно не отзывается.
        raise HTTPException(
            status_code=423,
            detail={
                "ok": False,
                "error": "screen_suspended",
                "message": "Показ временно приостановлен администратором",
            },
        )

    screen.is_online = True
    screen.last_active = utc_now_naive()
    db.commit()
    return screen
