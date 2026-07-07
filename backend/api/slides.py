from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from backend import crud, schemas, models
from backend.database import get_db
from backend.auth import get_current_user, require_hr_or_admin
from backend.websocket_manager import notify_clients

router = APIRouter()

@router.post("/slides", response_model=schemas.SlideOut)
def create_slide(
    slide: schemas.SlideCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    db_slide = crud.create_slide(db, slide)
    background_tasks.add_task(notify_clients, {"type": "slide_created", "id": db_slide.id})
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
    db_slide = crud.update_slide(db, slide_id, slide)
    if not db_slide:
        raise HTTPException(status_code=404, detail="Slide not found")
    background_tasks.add_task(notify_clients, {"type": "slide_updated", "id": db_slide.id})
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
    background_tasks.add_task(notify_clients, {"type": "slide_deleted", "id": slide_id})
    return {"ok": True}