"""Административные маршруты управления экранами.

Все маршруты этого router закрыты для неавторизованных пользователей на уровне
самого router. Экранный клиент использует отдельный router и отдельный device
token; пользовательский JWT туда не подставляется.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import require_hr_or_admin
from backend.config import config
from backend.database import get_db
from backend.routers.websocket import (
    notify_screen_credentials_revoked,
    notify_screen_resumed,
    notify_screen_suspended,
    notify_screens_updated,
)
from backend.screen_auth import (
    generate_pairing_code,
    pairing_expiry_from_now,
    rotate_screen_credentials,
)


router = APIRouter(dependencies=[Depends(require_hr_or_admin)])


def _get_screen_or_404(db: Session, screen_id: int) -> models.Screen:
    screen = db.get(models.Screen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Экран не найден")
    return screen


def _generate_unique_code(db: Session, *, except_screen_id: int | None = None) -> str:
    query = db.query(models.Screen.code)
    if except_screen_id is not None:
        query = query.filter(models.Screen.id != except_screen_id)
    existing_codes = {row[0] for row in query.all()}

    for _ in range(500):
        code = generate_pairing_code()
        if code not in existing_codes:
            return code
    raise HTTPException(status_code=503, detail="Не удалось найти свободный код")


@router.get("/screens/generate-code", response_model=schemas.ScreenPairingCodeOut)
def generate_screen_code(
    db: Session = Depends(get_db),
):
    """Генерирует 6-значный одноразовый pairing code."""
    return schemas.ScreenPairingCodeOut(
        code=_generate_unique_code(db),
        expires_in_seconds=config.SCREEN_PAIRING_TTL_MINUTES * 60,
    )


@router.post(
    "/screens",
    response_model=schemas.ScreenOut,
    status_code=status.HTTP_201_CREATED,
)
def create_screen(
    screen: schemas.ScreenCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    existing = (
        db.query(models.Screen)
        .filter(models.Screen.code == screen.code)
        .one_or_none()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Код уже используется")

    db_screen = models.Screen(
        **screen.model_dump(),
        pairing_expires_at=pairing_expiry_from_now(),
        device_token_hash=None,
        token_created_at=None,
        activated_at=None,
    )
    db.add(db_screen)
    db.commit()
    db.refresh(db_screen)

    background_tasks.add_task(
        notify_screens_updated,
        [db_screen.id],
        "screen_created",
    )
    return db_screen


@router.get("/screens", response_model=List[schemas.ScreenOut])
def get_all_screens(
    db: Session = Depends(get_db),
):
    return db.query(models.Screen).order_by(models.Screen.created_at.desc()).all()


@router.get("/screens/{screen_id}", response_model=schemas.ScreenOut)
def get_screen(
    screen_id: int,
    db: Session = Depends(get_db),
):
    return _get_screen_or_404(db, screen_id)


@router.put("/screens/{screen_id}", response_model=schemas.ScreenOut)
def update_screen(
    screen_id: int,
    screen_data: schemas.ScreenUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    screen = _get_screen_or_404(db, screen_id)
    for key, value in screen_data.model_dump(exclude_unset=True).items():
        setattr(screen, key, value)
    db.commit()
    db.refresh(screen)

    background_tasks.add_task(
        notify_screens_updated,
        [screen.id],
        "screen_updated",
    )
    return screen


@router.delete("/screens/{screen_id}")
def delete_screen(
    screen_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    screen = _get_screen_or_404(db, screen_id)
    screen_code = screen.code

    background_tasks.add_task(
        notify_screen_credentials_revoked,
        screen_code,
        "Экран удалён администратором",
    )
    db.delete(screen)
    db.commit()

    background_tasks.add_task(
        notify_screens_updated,
        [screen_id],
        "screen_deleted",
    )
    return {"ok": True}


@router.post("/screens/{screen_id}/connect")
def connect_screen(
    screen_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    screen = _get_screen_or_404(db, screen_id)
    status_changed = not bool(screen.is_connected)
    screen.is_connected = True
    db.commit()

    if status_changed:
        # Если старый WebSocket ещё не успел закрыться после suspend-события,
        # экран сможет восстановиться немедленно. Основной гарантированный
        # механизм восстановления — периодическая проверка /screen/me на клиенте.
        background_tasks.add_task(
            notify_screen_resumed,
            screen.code,
            "Показ снова разрешён администратором",
        )
        background_tasks.add_task(
            notify_screens_updated,
            [screen.id],
            "screen_connected",
        )
    return {
        "ok": True,
        "message": (
            f"Экран {screen.code} разрешён. "
            "Он восстановит соединение автоматически"
        ),
    }


@router.post("/screens/{screen_id}/disconnect")
def disconnect_screen(
    screen_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    screen = _get_screen_or_404(db, screen_id)
    status_changed = bool(screen.is_connected) or bool(screen.is_online)
    screen.is_connected = False
    screen.is_online = False
    db.commit()

    background_tasks.add_task(
        notify_screen_suspended,
        screen.code,
        "Показ временно приостановлен администратором",
    )
    if status_changed:
        background_tasks.add_task(
            notify_screens_updated,
            [screen.id],
            "screen_disconnected",
        )
    return {
        "ok": True,
        "message": (
            "Показ приостановлен. После повторного разрешения "
            "экран подключится без нового кода"
        ),
    }


@router.post(
    "/screens/{screen_id}/reset-pairing",
    response_model=schemas.ScreenPairingOut,
)
def reset_screen_pairing(
    screen_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Отзывает старый device token и выдаёт новый pairing code.

    Используется при утрате устройства, передаче экрана в ремонт или подозрении,
    что токен был скопирован. Старый экран немедленно теряет доступ.
    """
    screen = _get_screen_or_404(db, screen_id)
    old_code = screen.code

    try:
        code = rotate_screen_credentials(db, screen)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Это окончательный отзыв доверия к устройству, в отличие от disconnect.
    background_tasks.add_task(
        notify_screen_credentials_revoked,
        old_code,
        "Привязка экрана сброшена администратором",
    )

    background_tasks.add_task(
        notify_screens_updated,
        [screen.id],
        "screen_pairing_reset",
    )

    return schemas.ScreenPairingOut(
        screen_id=screen.id,
        code=code,
        pairing_expires_at=screen.pairing_expires_at,
    )
