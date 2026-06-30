from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from backend import crud, schemas
from backend.database import get_db

router = APIRouter()

@router.get("/slides/active", response_model=List[schemas.SlideOut])
def get_active_slides(db: Session = Depends(get_db)):
    return crud.get_active_slides(db)

@router.post("/slides/{slide_id}/view")
def track_view(slide_id: int, db: Session = Depends(get_db)):
    from backend.crud import increment_views
    increment_views(db, slide_id)
    return {"ok": True}