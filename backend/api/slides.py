from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from backend import crud, schemas, models
from backend.auth import get_current_user, require_hr_or_admin
from backend.routers.websocket import notify_schedule_updated, notify_slides_updated
from backend.schedule_generator import ScheduleGenerator
from datetime import datetime, timedelta, timezone
from backend.database import get_db, SessionLocal

router = APIRouter()

@router.post("/slides", response_model=schemas.SlideOut)
def create_slide(
    slide: schemas.SlideCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    db_slide = crud.create_slide(db, slide, current_user.id)
    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(notify_slides_updated, [db_slide.id], "slide_created")
    return db_slide

@router.get("/slides", response_model=List[schemas.SlideOut])
def get_all_slides(db: Session = Depends(get_db)):
    return crud.get_all_slides(db)

@router.get("/slides/{slide_id}", response_model=schemas.SlideOut)
def get_slide(slide_id: int, db: Session = Depends(get_db)):
    db_slide = crud.get_slide(db, slide_id)
    if not db_slide:
        raise HTTPException(status_code=404, detail="Slide not found")
    return db_slide

@router.put("/slides/{slide_id}", response_model=schemas.SlideOut)
def update_slide(
    slide_id: int,
    slide: schemas.SlideUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    db_slide = crud.update_slide(db, slide_id, slide, current_user.id)
    if not db_slide:
        raise HTTPException(status_code=404, detail="Slide not found")
    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(notify_slides_updated, [db_slide.id], "slide_updated")
    return db_slide

@router.delete("/slides/{slide_id}")
def delete_slide(
    slide_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    if not crud.delete_slide(db, slide_id):
        raise HTTPException(status_code=404, detail="Slide not found")
    background_tasks.add_task(regenerate_schedule_and_notify)
    background_tasks.add_task(notify_slides_updated, [slide_id], "slide_deleted")
    return {"ok": True}

async def regenerate_schedule_and_notify():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Лучше пересобирать от начала текущего часа,
        # чтобы текущее окно было цельным и не плясало от секунды создания слайда.
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
        previous_schedule_version=result.schedule_version - 1,
        from_=range_from.isoformat() + "Z",
        to=range_to.isoformat() + "Z",
        reason="schedule_regenerated",
    )