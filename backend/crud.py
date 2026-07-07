from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from datetime import datetime
from backend import models, schemas, auth

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

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(func.lower(models.User.username) == func.lower(username)).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(func.lower(models.User.email) == func.lower(email)).first()

def create_user(db: Session, user_data: schemas.UserCreate):
    hashed = auth.get_password_hash(user_data.password)
    db_user = models.User(
        username=user_data.username,
        password_hash=hashed,
        full_name=user_data.full_name,
        email=user_data.email,
        role=user_data.role or "hr"
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user(db: Session, user_id: int, user_data: schemas.UserUpdate):
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    update_dict = user_data.model_dump(exclude_unset=True, exclude={"password"})
    for key, value in update_dict.items():
        setattr(db_user, key, value)
    if user_data.password:
        db_user.password_hash = auth.get_password_hash(user_data.password)
    db.commit()
    db.refresh(db_user)
    return db_user

def delete_user(db: Session, user_id: int):
    db_user = get_user(db, user_id)
    if db_user:
        db.delete(db_user)
        db.commit()
        return True
    return False