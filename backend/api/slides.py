
"""CRUD слайдов и уведомление экранов об изменениях."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import crud, models, schemas
from backend.auth import require_hr_or_admin
from backend.database import SessionLocal, get_db
from backend.routers.websocket import notify_schedule_updated, notify_slides_updated
from backend.schedule_generator import ScheduleGenerator


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
    """Внутренний каталог слайдов доступен только HR/admin."""
    return crud.get_all_slides(db)


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


@router.delete("/slides/{slide_id}")
def delete_slide(
    slide_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_hr_or_admin),
):
    if not crud.delete_slide(db, slide_id):
        raise HTTPException(status_code=404, detail="Слайд не найден")

    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(
        notify_slides_updated,
        [slide_id],
        "slide_deleted",
    )
    return {"ok": True}


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
