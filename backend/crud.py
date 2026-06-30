from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from backend import models, schemas

def get_all_slides(db: Session):
    return db.query(models.Slide).order_by(models.Slide.created_at.desc()).all()

def get_active_slides(db: Session):
    now = datetime.now()
    return db.query(models.Slide).filter(
        and_(
            models.Slide.start_date <= now,
            models.Slide.end_date >= now,
            models.Slide.is_active == True
        )
    ).order_by(models.Slide.priority.desc()).all()

def get_slide(db: Session, slide_id: int):
    return db.query(models.Slide).filter(models.Slide.id == slide_id).first()

def create_slide(db: Session, slide_data: schemas.SlideCreate):
    db_slide = models.Slide(**slide_data.model_dump())
    db.add(db_slide)
    db.commit()
    db.refresh(db_slide)
    return db_slide

def update_slide(db: Session, slide_id: int, slide_data: schemas.SlideUpdate):
    db_slide = get_slide(db, slide_id)
    if not db_slide:
        return None
    update_data = slide_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_slide, key, value)
    db.commit()
    db.refresh(db_slide)
    return db_slide

def delete_slide(db: Session, slide_id: int):
    db_slide = get_slide(db, slide_id)
    if db_slide:
        db.delete(db_slide)
        db.commit()
        return True
    return False

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def create_user(db: Session, username: str, password_hash: str):
    db_user = models.User(username=username, password_hash=password_hash)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user