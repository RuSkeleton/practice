
"""Хеширование паролей, JWT и проверки ролей.

Файл не содержит HTTP-маршрутов. Здесь собрана повторно используемая логика,
чтобы правила паролей и авторизации не дублировались в разных router-файлах.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.config import config
from backend.database import get_db


# bcrypt автоматически создаёт уникальную соль для каждого пароля.
# В базе хранится только итоговый хеш, исходный пароль восстановить нельзя.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=True,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

ROLE_ADMIN = "admin"
ROLE_HR = "hr"
ROLE_VIEWER = "viewer"
VALID_ROLES = {ROLE_ADMIN, ROLE_HR, ROLE_VIEWER}

# Это не полноценная база утёкших паролей, а минимальная защита от очевидных
# значений, которые раньше использовались непосредственно в проекте.
COMMON_PASSWORDS = {
    "admin",
    "admin123",
    "password",
    "password123",
    "qwerty",
    "qwerty123",
    "12345",
    "123456",
    "12345678",
    "123456789",
    "111111",
    "hr12345",
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Сравнивает пароль с bcrypt-хешем без выброса внутренних ошибок наружу."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (TypeError, ValueError):
        return False


def get_password_hash(password: str) -> str:
    """Создаёт bcrypt-хеш пароля."""
    return pwd_context.hash(password)


def validate_role(role: str | None) -> str:
    """Нормализует роль и запрещает произвольные строки."""
    normalized = (role or ROLE_HR).strip().lower()
    if normalized not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Некорректная роль пользователя")
    return normalized


def validate_password_strength(
    password: str,
    *,
    username: str | None = None,
    allow_unsafe_dev_password: bool = False,
) -> None:
    """Проверяет пароль до хеширования.

    ``allow_unsafe_dev_password`` используется только внутренним dev-bootstrap.
    Пользователи, создаваемые через API, проходят обычную политику даже в dev.
    """
    if allow_unsafe_dev_password and config.DEV_MODE:
        return

    if not password:
        raise HTTPException(status_code=400, detail="Пароль не может быть пустым")

    if len(password) < config.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Пароль должен быть не короче "
                f"{config.PASSWORD_MIN_LENGTH} символов"
            ),
        )

    # bcrypt обрабатывает максимум 72 байта. Явная ошибка понятнее, чем
    # неочевидное усечение или исключение глубоко внутри passlib.
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400,
            detail="Пароль слишком длинный для bcrypt: максимум 72 байта",
        )

    normalized_password = password.strip().lower()
    normalized_username = (username or "").strip().lower()

    if normalized_password in COMMON_PASSWORDS:
        raise HTTPException(status_code=400, detail="Пароль слишком распространённый")

    if normalized_username and normalized_username in normalized_password:
        raise HTTPException(status_code=400, detail="Пароль не должен содержать логин")

    if config.PASSWORD_REQUIRE_MIXED:
        has_letter = any(char.isalpha() for char in password)
        has_digit = any(char.isdigit() for char in password)
        if not has_letter or not has_digit:
            raise HTTPException(
                status_code=400,
                detail="Пароль должен содержать хотя бы одну букву и одну цифру",
            )


def create_access_token(
    *,
    user: models.User,
    expires_delta: timedelta | None = None,
) -> str:
    """Создаёт короткоживущий access token.

    В ``sub`` хранится неизменяемый ID пользователя, а не логин. Если admin
    переименует пользователя, его токен продолжит однозначно ссылаться на ту же
    запись. Роль всё равно повторно читается из БД при каждом запросе.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + (
        expires_delta
        or timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "ver": int(user.auth_version or 1),
        "type": "access",
        "iat": now,
        "exp": expires_at,
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)


def authenticate_user(
    db: Session,
    username: str,
    password: str,
) -> models.User | None:
    """Проверяет логин, пароль и активность учётной записи."""
    normalized_username = username.strip().lower()
    user = (
        db.query(models.User)
        .filter(func.lower(models.User.username) == normalized_username)
        .one_or_none()
    )

    # Ответ login endpoint остаётся одинаковым для неизвестного пользователя,
    # неправильного пароля и отключённой учётной записи.
    if user is None or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """Проверяет подпись JWT и загружает актуального пользователя из БД."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            config.SECRET_KEY,
            algorithms=[config.ALGORITHM],
        )
        if payload.get("type") != "access":
            raise credentials_exception
        user_id = int(payload.get("sub"))
        token_version = int(payload.get("ver"))
    except (JWTError, TypeError, ValueError):
        raise credentials_exception

    user = db.get(models.User, user_id)
    if user is None:
        raise credentials_exception
    if token_version != int(user.auth_version or 1):
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Пользователь отключён")
    return user


def require_admin(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """Dependency для endpoint'ов, доступных только администратору."""
    if current_user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Требуется роль администратора")
    return current_user


def require_hr_or_admin(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """Dependency для управления слайдами и экранами."""
    if current_user.role not in {ROLE_HR, ROLE_ADMIN}:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для управления системой",
        )
    return current_user
