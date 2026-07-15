"""HTTP API входа и управления пользователями.

Маршруты разделены на три группы с политикой deny-by-default:
* public_router: только вход и безопасная конфигурация страницы входа;
* account_router: действия любого авторизованного пользователя;
* admin_router: управление пользователями только для admin.

Публичная регистрация удалена. Для разработки остаётся явный dev-bootstrap,
а в рабочей системе новых пользователей создаёт администратор.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import auth, crud, models
from backend.config import config
from backend.database import get_db
from backend.rate_limit import SlidingWindowRateLimiter
from backend.routers.websocket import notify_users_updated
from backend.schemas import (
    LoginResponse,
    PasswordChange,
    PublicConfigOut,
    UserCreate,
    UserOut,
    UserUpdate,
)


router = APIRouter()
public_router = APIRouter()
account_router = APIRouter(
    dependencies=[Depends(auth.get_current_user)],
)
admin_router = APIRouter(
    dependencies=[Depends(auth.require_admin)],
)

_login_account_limiter = SlidingWindowRateLimiter(
    max_attempts=config.LOGIN_MAX_FAILED_ATTEMPTS_PER_ACCOUNT,
    window_seconds=config.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)
_login_ip_limiter = SlidingWindowRateLimiter(
    max_attempts=config.LOGIN_MAX_FAILED_ATTEMPTS_PER_IP,
    window_seconds=config.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)


def _utc_now_naive() -> datetime:
    """Модели проекта пока хранят UTC как naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _raise_if_login_limited(*, ip_key: str, account_key: str) -> None:
    states = (
        _login_ip_limiter.check(ip_key),
        _login_account_limiter.check(account_key),
    )
    blocked = [state for state in states if not state.allowed]
    if not blocked:
        return

    retry_after = max(state.retry_after_seconds for state in blocked)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Слишком много неудачных попыток входа. Повторите позже",
        headers={"Retry-After": str(retry_after)},
    )


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


# ---------------------------------------------------------------------------
# Явно публичные маршруты
# ---------------------------------------------------------------------------

@public_router.get("/public-config", response_model=PublicConfigOut)
def get_public_config() -> PublicConfigOut:
    """Возвращает только настройки, которые разрешено видеть до входа."""
    show_hints = bool(config.DEV_MODE and config.SHOW_DEV_LOGIN_HINTS)
    return PublicConfigOut(
        dev_mode=config.DEV_MODE,
        show_dev_login_hints=show_hints,
        dev_username=config.DEV_HR_USERNAME if show_hints else None,
        dev_password=config.DEV_HR_PASSWORD if show_hints else None,
    )


@public_router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Проверяет пароль и выдаёт подписанный, отзывной access token."""
    normalized_username = form_data.username.strip().lower()
    ip_key = _client_ip(request)
    account_key = f"{ip_key}:{normalized_username}"
    _raise_if_login_limited(ip_key=ip_key, account_key=account_key)

    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        _login_ip_limiter.record_failure(ip_key)
        _login_account_limiter.record_failure(account_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _login_account_limiter.reset(account_key)
    user.last_login = _utc_now_naive()
    db.commit()

    return LoginResponse(
        access_token=auth.create_access_token(user=user),
        token_type="bearer",
        role=user.role,
        expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# Любой авторизованный пользователь
# ---------------------------------------------------------------------------

@account_router.get("/users/me", response_model=UserOut)
def get_current_user_info(
    current_user: models.User = Depends(auth.get_current_user),
):
    return current_user


@account_router.post("/auth/change-password")
def change_own_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Меняет пароль и немедленно отзывает все ранее выданные JWT."""
    if not auth.verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    if auth.verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Новый пароль совпадает с текущим")

    auth.validate_password_strength(
        payload.new_password,
        username=current_user.username,
    )
    current_user.password_hash = auth.get_password_hash(payload.new_password)
    current_user.auth_version = int(current_user.auth_version or 1) + 1
    db.commit()
    return {"ok": True, "reauthentication_required": True}


# ---------------------------------------------------------------------------
# Только администратор
# ---------------------------------------------------------------------------

@admin_router.get("/users", response_model=list[UserOut])
def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return crud.get_users(db, skip=skip, limit=min(limit, 500))


@admin_router.get("/users/{user_id}", response_model=UserOut)
def get_user_by_id(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@admin_router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_new_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    _ensure_username_available(db, user_data.username)
    _ensure_email_available(db, str(user_data.email) if user_data.email else None)

    try:
        created_user = crud.create_user(db, user_data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Пользователь с такими данными уже существует",
        ) from exc

    background_tasks.add_task(
        notify_users_updated,
        [created_user.id],
        "user_created",
    )
    return created_user


@admin_router.put("/users/{user_id}", response_model=UserOut)
def update_existing_user(
    user_id: int,
    user_data: UserUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
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

    background_tasks.add_task(
        notify_users_updated,
        [updated_user.id],
        "user_updated",
    )
    return updated_user


@admin_router.delete("/users/{user_id}")
def delete_existing_user(
    user_id: int,
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(
        notify_users_updated,
        [user_id],
        "user_deleted",
    )
    return {"ok": True}


# Статические /users/me и /auth/change-password подключаются раньше динамического
# /users/{user_id}, поэтому FastAPI не пытается разобрать "me" как integer.
router.include_router(public_router)
router.include_router(account_router)
router.include_router(admin_router)
