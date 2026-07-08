from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from backend import auth, crud, schemas
from backend.database import get_db
from backend.config import config

from backend.crud import (
    get_users,
    get_user,
    get_user_by_username,
    get_user_by_email,
    create_user,
    update_user,
    delete_user
)
from backend.schemas import UserCreate, UserUpdate, UserOut
from backend.auth import get_current_user, require_admin, require_hr_or_admin

router = APIRouter()

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}

@router.post("/register")
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = crud.get_user_by_username(db, user_data.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = auth.get_password_hash(user_data.password)
    user = crud.create_user(db, user_data.username, hashed_password)
    return {"message": "User created", "username": user.username}

@router.get("/users", response_model=list[UserOut])
def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin)
):
    return get_users(db, skip=skip, limit=limit)

@router.get("/users/me", response_model=UserOut)
def get_current_user_info(current_user: models.User = Depends(get_current_user)):
    return current_user

@router.get("/users/{user_id}", response_model=UserOut)
def get_user_by_id(
    user_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin)
):
    user = get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user

@router.post("/users", response_model=UserOut)
def create_new_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin)
):
    if get_user_by_username(db, user_data.username):
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
    if user_data.email and get_user_by_email(db, user_data.email):
        raise HTTPException(status_code=400, detail="Email уже используется")
    return create_user(db, user_data)

@router.put("/users/{user_id}", response_model=UserOut)
def update_existing_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin)
):
    user = update_user(db, user_id, user_data)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user

@router.delete("/users/{user_id}")
def delete_existing_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(require_admin)
):
    # Запрещаем удалять самого себя
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить свою учётную запись")
    if not delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"ok": True}