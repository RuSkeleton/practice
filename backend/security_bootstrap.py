
"""Создание первого администратора и dev-учётных записей.

Bootstrap выполняется во время запуска FastAPI, но только после того, как схема
базы приведена к актуальному состоянию командой ``alembic upgrade head``.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import auth, models
from backend.config import config


# Эти пары проверяются при production-запуске независимо от настроек dev-файла.
# В ошибке пароль не печатается, чтобы не приучать логи содержать секреты.
CANONICAL_INSECURE_CREDENTIALS = {
    "admin": "admin123",
    "hr": "12345",
}


def _find_user_by_username(db: Session, username: str) -> models.User | None:
    return (
        db.query(models.User)
        .filter(func.lower(models.User.username) == username.strip().lower())
        .one_or_none()
    )


def _create_or_update_dev_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str,
    full_name: str,
) -> None:
    """Создаёт dev-пользователя, не сбрасывая пароль без явного флага.

    Раньше пароль admin мог возвращаться к admin123 при каждом запуске. Теперь
    существующий пароль сохраняется. Для осознанного сброса используется
    DEV_BOOTSTRAP_RESET_PASSWORDS=true.
    """
    user = _find_user_by_username(db, username)

    if user is None:
        user = models.User(
            username=username,
            password_hash=auth.get_password_hash(password),
            role=role,
            full_name=full_name,
            is_active=True,
        )
        db.add(user)
    else:
        user.role = role
        user.full_name = user.full_name or full_name
        user.is_active = True
        if config.DEV_BOOTSTRAP_RESET_PASSWORDS:
            user.password_hash = auth.get_password_hash(password)
            user.auth_version = int(user.auth_version or 1) + 1

    db.commit()


def _create_initial_admin(db: Session) -> None:
    """Создаёт единственного первого администратора пустой production-базы."""
    if not config.INITIAL_ADMIN_PASSWORD:
        raise RuntimeError(
            "The users table is empty. Set INITIAL_ADMIN_PASSWORD for the first "
            "production start, or use the explicit development configuration."
        )

    try:
        auth.validate_password_strength(
            config.INITIAL_ADMIN_PASSWORD,
            username=config.INITIAL_ADMIN_USERNAME,
        )
    except HTTPException as exc:
        raise RuntimeError(
            f"INITIAL_ADMIN_PASSWORD does not satisfy the password policy: {exc.detail}"
        ) from exc

    if _find_user_by_username(db, config.INITIAL_ADMIN_USERNAME) is not None:
        raise RuntimeError("INITIAL_ADMIN_USERNAME is already occupied")

    user = models.User(
        username=config.INITIAL_ADMIN_USERNAME,
        password_hash=auth.get_password_hash(config.INITIAL_ADMIN_PASSWORD),
        role=auth.ROLE_ADMIN,
        full_name=config.INITIAL_ADMIN_FULL_NAME,
        email=(config.INITIAL_ADMIN_EMAIL.strip() if config.INITIAL_ADMIN_EMAIL else None),
        is_active=True,
    )
    db.add(user)
    db.commit()
    print(f"Created initial administrator: {user.username}")


def _assert_no_insecure_default_credentials(db: Session) -> None:
    """Запрещает production-старт, пока живы известные дефолтные пароли."""
    credentials = dict(CANONICAL_INSECURE_CREDENTIALS)

    # Если команда меняла dev-логины/пароли, эти значения тоже считаются
    # разработческими и не должны случайно попасть в production.
    credentials[config.DEV_ADMIN_USERNAME] = config.DEV_ADMIN_PASSWORD
    credentials[config.DEV_HR_USERNAME] = config.DEV_HR_PASSWORD

    for username, password in credentials.items():
        user = _find_user_by_username(db, username)
        if user and auth.verify_password(password, user.password_hash):
            raise RuntimeError(
                f"Unsafe development password is still valid for user '{username}'. "
                "Change the password before starting production."
            )


def bootstrap_auth(db: Session) -> None:
    """Единая точка начальной настройки доступа.

    Development:
      * dev-аккаунты создаются только при ENABLE_DEV_BOOTSTRAP=true;
      * пароль существующего аккаунта не сбрасывается без отдельного флага.

    Production:
      * известные пароли admin123/12345 запрещены;
      * в пустой базе первый admin создаётся только из INITIAL_ADMIN_*.
    """
    user_count = db.query(models.User).count()

    if config.DEV_MODE:
        if config.ENABLE_DEV_BOOTSTRAP:
            _create_or_update_dev_user(
                db,
                username=config.DEV_ADMIN_USERNAME,
                password=config.DEV_ADMIN_PASSWORD,
                role=auth.ROLE_ADMIN,
                full_name="Development Administrator",
            )
            _create_or_update_dev_user(
                db,
                username=config.DEV_HR_USERNAME,
                password=config.DEV_HR_PASSWORD,
                role=auth.ROLE_HR,
                full_name="Development HR",
            )
            print("Development auth bootstrap is enabled")
            if config.SHOW_DEV_LOGIN_HINTS:
                print(
                    "Dev login hints are enabled for the browser login page "
                    f"({config.DEV_HR_USERNAME})"
                )
            if config.SECRET_KEY_IS_EPHEMERAL:
                print("JWT secret is ephemeral; tokens expire after server restart")
            return

        if user_count == 0:
            raise RuntimeError(
                "No users exist and ENABLE_DEV_BOOTSTRAP=false. Copy "
                ".env.development.example to .env or create an initial admin."
            )
        return

    if user_count == 0:
        _create_initial_admin(db)

    _assert_no_insecure_default_credentials(db)
