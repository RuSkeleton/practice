"""Административные маршруты управления экранами.

Маршруты экранного клиента (activate/schedule/slides batch) находятся отдельно
в ``backend/routers/screens.py``. Такое разделение убирает прежние дубликаты
``/screens/activate`` и не смешивает права HR с протоколом экранного клиента.
"""

from __future__ import annotations

import secrets
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import require_hr_or_admin
from backend.database import get_db
from backend.routers.websocket import notify_screen_disabled


router = APIRouter()


def _get_screen_or_404(db: Session, screen_id: int) -> models.Screen:
    screen = db.get(models.Screen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Экран не найден")
    return screen


@router.get("/screens/generate-code")
def generate_screen_code(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    """Генерирует свободный pairing-код.

    ``secrets`` выбран вместо ``random``: он предназначен для значений,
    связанных с доступом. Пространство из 1000 кодов всё равно мало — это будет
    заменено на одноразовый pairing + постоянный screen token следующим этапом.
    """
    existing_codes = {row[0] for row in db.query(models.Screen.code).all()}
    for _ in range(200):
        code = f"{secrets.randbelow(1000):03d}"
        if code not in existing_codes:
            return {"code": code}
    raise HTTPException(status_code=503, detail="Не удалось найти свободный код")


@router.post(
    "/screens",
    response_model=schemas.ScreenOut,
    status_code=status.HTTP_201_CREATED,
)
def create_screen(
    screen: schemas.ScreenCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    existing = (
        db.query(models.Screen)
        .filter(models.Screen.code == screen.code)
        .one_or_none()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Код уже используется")

    db_screen = models.Screen(**screen.model_dump())
    db.add(db_screen)
    db.commit()
    db.refresh(db_screen)
    return db_screen


@router.get("/screens", response_model=List[schemas.ScreenOut])
def get_all_screens(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    # Viewer не получает список коротких кодов экранов.
    return db.query(models.Screen).order_by(models.Screen.created_at.desc()).all()


@router.get("/screens/{screen_id}", response_model=schemas.ScreenOut)
def get_screen(
    screen_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    return _get_screen_or_404(db, screen_id)


@router.put("/screens/{screen_id}", response_model=schemas.ScreenOut)
def update_screen(
    screen_id: int,
    screen_data: schemas.ScreenUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    screen = _get_screen_or_404(db, screen_id)
    for key, value in screen_data.model_dump(exclude_unset=True).items():
        setattr(screen, key, value)
    db.commit()
    db.refresh(screen)
    return screen


@router.delete("/screens/{screen_id}")
def delete_screen(
    screen_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    screen = _get_screen_or_404(db, screen_id)
    screen_code = screen.code

    # Сначала уведомляем текущий WebSocket, затем удаляем запись.
    background_tasks.add_task(
        notify_screen_disabled,
        screen_code,
        "Экран удалён администратором",
    )
    db.delete(screen)
    db.commit()
    return {"ok": True}


@router.post("/screens/{screen_id}/connect")
def connect_screen(
    screen_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    screen = _get_screen_or_404(db, screen_id)
    screen.is_connected = True
    db.commit()
    return {"ok": True, "message": f"Экран {screen.code} подключён"}


@router.post("/screens/{screen_id}/disconnect")
def disconnect_screen(
    screen_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    screen = _get_screen_or_404(db, screen_id)
    screen.is_connected = False
    screen.is_online = False
    db.commit()

    background_tasks.add_task(
        notify_screen_disabled,
        screen.code,
        "Экран отключён администратором",
    )
    return {"ok": True}
