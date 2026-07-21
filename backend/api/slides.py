
"""CRUD слайдов и уведомление экранов об изменениях."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import crud, models, schemas
from backend.emergency_presets import (
    get_emergency_presets,
    set_emergency_preset_active,
)
from backend.auth import require_hr_or_admin
from backend.database import SessionLocal, get_db
from backend.routers.websocket import notify_schedule_updated, notify_slides_updated
from backend.schedule_generator import SCHEDULE_VERSION_KEY, ScheduleGenerator


router = APIRouter(dependencies=[Depends(require_hr_or_admin)])


@router.post(
    "/slides",
    response_model=schemas.SlideOut,
    status_code=status.HTTP_201_CREATED,
)
def create_slide(
    slide: schemas.SlideCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    if slide.is_emergency:
        raise HTTPException(
            status_code=400,
            detail="Аварийные слайды создаются и запускаются через меню аварийных пресетов",
        )

    db_slide = crud.create_slide(db, slide, current_user.id)
    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(
        notify_slides_updated,
        [db_slide.id],
        "slide_created",
    )
    return db_slide


@router.get("/slides", response_model=List[schemas.SlideOut])
def get_all_slides(
    db: Session = Depends(get_db),
):
    """Обычные слайды и активные аварийные слайды для верхней части списка."""
    return crud.get_admin_slides(db)


@router.get("/slides/{slide_id}", response_model=schemas.SlideOut)
def get_slide(
    slide_id: int,
    db: Session = Depends(get_db),
):
    db_slide = crud.get_slide(db, slide_id)
    if db_slide is None:
        raise HTTPException(status_code=404, detail="Слайд не найден")
    return db_slide


@router.put("/slides/{slide_id}", response_model=schemas.SlideOut)
def update_slide(
    slide_id: int,
    slide: schemas.SlideUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    existing = crud.get_slide(db, slide_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Слайд не найден")

    if existing.is_emergency:
        # Редактор меняет только содержимое пресета. Состояние аварийного режима,
        # тип тревоги и период управляются отдельными быстрыми действиями.
        slide = slide.model_copy(
            update={
                "is_emergency": True,
                "alarm_type": existing.alarm_type,
                "is_active": existing.is_active,
                "start_date": existing.start_date,
                "end_date": existing.end_date,
                "duration_slots": 1,
                "frequency_mode": 1,
                "hard_interval": None,
            }
        )
    elif slide.is_emergency is True:
        raise HTTPException(
            status_code=400,
            detail="Обычный слайд нельзя превратить в аварийный; используйте аварийные пресеты",
        )

    try:
        db_slide = crud.update_slide(db, slide_id, slide, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if db_slide is None:
        raise HTTPException(status_code=404, detail="Слайд не найден")

    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(
        notify_slides_updated,
        [db_slide.id],
        "slide_updated",
    )
    return db_slide


@router.get("/emergency-presets", response_model=List[schemas.SlideOut])
def list_emergency_presets(
    db: Session = Depends(get_db),
):
    """Отдельный каталог встроенных аварийных пресетов."""
    return get_emergency_presets(db)


@router.post(
    "/emergency-presets/{slide_id}/activate",
    response_model=schemas.SlideOut,
)
def activate_emergency_preset(
    slide_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    slide = set_emergency_preset_active(
        db,
        slide_id,
        is_active=True,
        user_id=current_user.id,
    )
    if slide is None:
        raise HTTPException(status_code=404, detail="Аварийный пресет не найден")

    background_tasks.add_task(notify_emergency_changed, "emergency_activated")
    background_tasks.add_task(
        notify_slides_updated,
        [slide.id],
        "emergency_activated",
    )
    return slide


@router.post(
    "/emergency-presets/{slide_id}/deactivate",
    response_model=schemas.SlideOut,
)
def deactivate_emergency_preset(
    slide_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    slide = set_emergency_preset_active(
        db,
        slide_id,
        is_active=False,
        user_id=current_user.id,
    )
    if slide is None:
        raise HTTPException(status_code=404, detail="Аварийный пресет не найден")

    background_tasks.add_task(notify_emergency_changed, "emergency_deactivated")
    background_tasks.add_task(
        notify_slides_updated,
        [slide.id],
        "emergency_deactivated",
    )
    return slide


@router.delete("/slides/{slide_id}")
def delete_slide(
    slide_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    db_slide = crud.get_slide(db, slide_id)
    if db_slide is None:
        raise HTTPException(status_code=404, detail="Слайд не найден")
    if db_slide.is_emergency:
        raise HTTPException(
            status_code=400,
            detail="Встроенный аварийный пресет нельзя удалить; его можно отредактировать или отключить",
        )

    if not crud.delete_slide(db, slide_id):
        raise HTTPException(status_code=404, detail="Слайд не найден")

    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(
        notify_slides_updated,
        [slide_id],
        "slide_deleted",
    )
    return {"ok": True}


async def notify_emergency_changed(reason: str) -> None:
    """Немедленно сообщает экранам, что аварийная очередь изменилась."""
    db = SessionLocal()
    try:
        setting = (
            db.query(models.SystemSetting)
            .filter(models.SystemSetting.setting_key == SCHEDULE_VERSION_KEY)
            .one_or_none()
        )
        schedule_version = int(setting.int_value or 0) if setting else 0
    finally:
        db.close()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await notify_schedule_updated(
        mode="full",
        schedule_version=schedule_version,
        previous_schedule_version=max(0, schedule_version - 1),
        from_=now.isoformat() + "Z",
        to=(now + timedelta(days=3)).isoformat() + "Z",
        reason=reason,
    )


async def regenerate_schedule_and_notify() -> None:
    """Пересобирает расписание после изменения контента."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        range_from = now.replace(minute=0, second=0, microsecond=0)
        range_to = range_from + timedelta(days=3)

        generator = ScheduleGenerator(db)
        result = generator.generate_schedule(
            window_size_seconds=3600,
            slot_duration_seconds=15,
            range_from=range_from,
            range_to=range_to,
        )
    finally:
        db.close()

    await notify_schedule_updated(
        mode="full",
        schedule_version=result.schedule_version,
        previous_schedule_version=max(0, result.schedule_version - 1),
        from_=range_from.isoformat() + "Z",
        to=range_to.isoformat() + "Z",
        reason="schedule_regenerated",
    )
