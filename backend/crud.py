"""Операции чтения и изменения сущностей через SQLAlchemy."""

from __future__ import annotations

from datetime import timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import auth, models, schemas


# ---------------------------------------------------------------------------
# Слайды
# ---------------------------------------------------------------------------


def _to_utc_naive(value):
    """Внутри SQLite храним UTC без tzinfo, наружу сериализуем отдельно."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_all_slides(db: Session):
    return db.query(models.Slide).order_by(models.Slide.created_at.desc()).all()


def get_slide(db: Session, slide_id: int):
    return db.query(models.Slide).filter(models.Slide.id == slide_id).first()


def create_slide(
    db: Session,
    slide_data: schemas.SlideCreate,
    user_id: Optional[int] = None,
):
    data = slide_data.model_dump()
    data["start_date"] = _to_utc_naive(data["start_date"])
    data["end_date"] = _to_utc_naive(data["end_date"])

    db_slide = models.Slide(
        **data,
        created_by=user_id,
        updated_by=user_id,
        revision=1,
    )
    db.add(db_slide)
    db.commit()
    db.refresh(db_slide)
    return db_slide


def update_slide(
    db: Session,
    slide_id: int,
    slide_data: schemas.SlideUpdate,
    user_id: Optional[int] = None,
):
    db_slide = get_slide(db, slide_id)
    if db_slide is None:
        return None

    update_data = slide_data.model_dump(exclude_unset=True)
    if "start_date" in update_data:
        update_data["start_date"] = _to_utc_naive(update_data["start_date"])
    if "end_date" in update_data:
        update_data["end_date"] = _to_utc_naive(update_data["end_date"])

    # Для частичного PUT/PATCH Pydantic не видит итоговое состояние объекта,
    # поэтому проверяем период и hard_interval после объединения с данными БД.
    final_start = update_data.get("start_date", db_slide.start_date)
    final_end = update_data.get("end_date", db_slide.end_date)
    if final_end <= final_start:
        raise ValueError("Дата окончания должна быть позже даты начала")

    final_frequency = update_data.get("frequency_mode", db_slide.frequency_mode)
    final_interval = update_data.get("hard_interval", db_slide.hard_interval)
    if final_frequency == 4 and final_interval is None:
        raise ValueError("Для жёсткого режима требуется hard_interval")
    if final_frequency != 4 and final_interval is not None:
        raise ValueError("hard_interval разрешён только для frequency_mode=4")

    if update_data:
        db_slide.revision += 1
        db_slide.updated_by = user_id

    for key, value in update_data.items():
        setattr(db_slide, key, value)

    db.commit()
    db.refresh(db_slide)
    return db_slide


def delete_slide(db: Session, slide_id: int) -> bool:
    db_slide = get_slide(db, slide_id)
    if db_slide is None:
        return False
    db.delete(db_slide)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------


def get_users(db: Session, skip: int = 0, limit: int = 100):
    return (
        db.query(models.User)
        .order_by(models.User.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_user(db: Session, user_id: int):
    return db.get(models.User, user_id)


def get_user_by_username(db: Session, username: str):
    return (
        db.query(models.User)
        .filter(func.lower(models.User.username) == username.strip().lower())
        .first()
    )


def get_user_by_email(db: Session, email: str):
    return (
        db.query(models.User)
        .filter(func.lower(models.User.email) == email.strip().lower())
        .first()
    )


def create_user(
    db: Session,
    user_data: schemas.UserCreate,
    *,
    allow_unsafe_dev_password: bool = False,
):
    username = user_data.username.strip()
    role = auth.validate_role(user_data.role)
    auth.validate_password_strength(
        user_data.password,
        username=username,
        allow_unsafe_dev_password=allow_unsafe_dev_password,
    )

    db_user = models.User(
        username=username,
        password_hash=auth.get_password_hash(user_data.password),
        full_name=user_data.full_name,
        email=(str(user_data.email).lower() if user_data.email else None),
        role=role,
        is_active=True,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(
    db: Session,
    user_id: int,
    user_data: schemas.UserUpdate,
    *,
    allow_unsafe_dev_password: bool = False,
):
    db_user = get_user(db, user_id)
    if db_user is None:
        return None

    update_dict = user_data.model_dump(exclude_unset=True, exclude={"password"})

    if "username" in update_dict and update_dict["username"] is not None:
        update_dict["username"] = update_dict["username"].strip()
    if "email" in update_dict:
        update_dict["email"] = (
            str(update_dict["email"]).lower() if update_dict["email"] else None
        )
    if "role" in update_dict and update_dict["role"] is not None:
        update_dict["role"] = auth.validate_role(update_dict["role"])

    for key, value in update_dict.items():
        setattr(db_user, key, value)

    if user_data.password:
        auth.validate_password_strength(
            user_data.password,
            username=db_user.username,
            allow_unsafe_dev_password=allow_unsafe_dev_password,
        )
        db_user.password_hash = auth.get_password_hash(user_data.password)

    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> bool:
    db_user = get_user(db, user_id)
    if db_user is None:
        return False
    db.delete(db_user)
    db.commit()
    return True
