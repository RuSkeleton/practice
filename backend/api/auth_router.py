"""HTTP API входа и управления пользователями."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import auth, crud, models
from backend.config import config
from backend.database import get_db
from backend.schemas import (
    LoginResponse,
    PasswordChange,
    PublicConfigOut,
    UserCreate,
    UserOut,
    UserUpdate,
)


router = APIRouter()


def _utc_now_naive() -> datetime:
    """Модели проекта пока хранят UTC как naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _active_admin_count(db: Session) -> int:
    return (
        db.query(models.User)
        .filter(
            models.User.role == auth.ROLE_ADMIN,
            models.User.is_active.is_(True),
        )
        .count()
    )


def _ensure_username_available(
    db: Session,
    username: str,
    *,
    except_user_id: int | None = None,
) -> None:
    existing = crud.get_user_by_username(db, username)
    if existing and existing.id != except_user_id:
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")


def _ensure_email_available(
    db: Session,
    email: str | None,
    *,
    except_user_id: int | None = None,
) -> None:
    if not email:
        return
    existing = crud.get_user_by_email(db, str(email))
    if existing and existing.id != except_user_id:
        raise HTTPException(status_code=400, detail="Email уже используется")


def _ensure_not_breaking_last_admin(
    db: Session,
    user: models.User,
    update_data: UserUpdate,
) -> None:
    """Не даёт отключить или разжаловать последнего активного admin."""
    if user.role != auth.ROLE_ADMIN or not user.is_active:
        return
    if _active_admin_count(db) > 1:
        return

    will_be_inactive = update_data.is_active is False
    will_stop_being_admin = (
        update_data.role is not None and update_data.role != auth.ROLE_ADMIN
    )
    if will_be_inactive or will_stop_being_admin:
        raise HTTPException(
            status_code=400,
            detail=(
                "Нельзя отключить или изменить роль последнего "
                "активного администратора"
            ),
        )



@router.get("/public-config", response_model=PublicConfigOut)
def get_public_config() -> PublicConfigOut:
    """Возвращает только настройки, которые разрешено видеть до входа.

    Пароль появляется здесь исключительно при двух явных dev-флагах:
    DEV_MODE=true и SHOW_DEV_LOGIN_HINTS=true.
    """
    show_hints = bool(config.DEV_MODE and config.SHOW_DEV_LOGIN_HINTS)
    return PublicConfigOut(
        dev_mode=config.DEV_MODE,
        show_dev_login_hints=show_hints,
        dev_username=config.DEV_HR_USERNAME if show_hints else None,
        dev_password=config.DEV_HR_PASSWORD if show_hints else None,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Проверяет пароль и выдаёт подписанный access token."""
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        # Намеренно не сообщаем, существовал ли логин и была ли запись отключена.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.last_login = _utc_now_naive()
    db.commit()

    return LoginResponse(
        access_token=auth.create_access_token(user=user),
        token_type="bearer",
        role=user.role,
        expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=UserOut)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db),
) -> models.User:
    """Неавторизованная регистрация существует только как dev-инструмент."""
    if not (config.DEV_MODE and config.ENABLE_PUBLIC_REGISTER_IN_DEV):
        raise HTTPException(status_code=403, detail="Публичная регистрация отключена")

    _ensure_username_available(db, user_data.username)
    _ensure_email_available(db, str(user_data.email) if user_data.email else None)
    return crud.create_user(db, user_data)


@router.get("/users", response_model=list[UserOut])
def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    return crud.get_users(db, skip=skip, limit=min(limit, 500))


@router.get("/users/me", response_model=UserOut)
def get_current_user_info(
    current_user: models.User = Depends(auth.get_current_user),
):
    return current_user


@router.post("/auth/change-password")
def change_own_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Позволяет пользователю менять свой пароль без доступа к user CRUD."""
    if not auth.verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    if auth.verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Новый пароль совпадает с текущим")

    auth.validate_password_strength(
        payload.new_password,
        username=current_user.username,
    )
    current_user.password_hash = auth.get_password_hash(payload.new_password)
    db.commit()
    return {"ok": True}


@router.get("/users/{user_id}", response_model=UserOut)
def get_user_by_id(
    user_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_new_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    _ensure_username_available(db, user_data.username)
    _ensure_email_available(db, str(user_data.email) if user_data.email else None)

    try:
        return crud.create_user(db, user_data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Пользователь с такими данными уже существует",
        ) from exc


@router.put("/users/{user_id}", response_model=UserOut)
def update_existing_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.require_admin),
):
    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user_data.username:
        _ensure_username_available(
            db,
            user_data.username,
            except_user_id=user_id,
        )
    if user_data.email:
        _ensure_email_available(
            db,
            str(user_data.email),
            except_user_id=user_id,
        )

    _ensure_not_breaking_last_admin(db, user, user_data)

    try:
        updated_user = crud.update_user(db, user_id, user_data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Пользователь с такими данными уже существует",
        ) from exc

    if updated_user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return updated_user


@router.delete("/users/{user_id}")
def delete_existing_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.require_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить свою учётную запись")

    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if (
        user.role == auth.ROLE_ADMIN
        and user.is_active
        and _active_admin_count(db) <= 1
    ):
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить последнего активного администратора",
        )

    crud.delete_user(db, user_id)
    return {"ok": True}
