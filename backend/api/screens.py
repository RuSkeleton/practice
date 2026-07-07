from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import List
import random
from datetime import datetime
from backend import models, schemas
from backend.database import get_db
from backend.auth import get_current_user, require_hr_or_admin

router = APIRouter()

@router.post("/screens", response_model=schemas.ScreenOut)
def create_screen(
    screen: schemas.ScreenCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin)
):
    existing = db.query(models.Screen).filter(models.Screen.code == screen.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Code already in use")
    db_screen = models.Screen(**screen.model_dump())
    db.add(db_screen)
    db.commit()
    db.refresh(db_screen)
    return db_screen

@router.get("/screens", response_model=List[schemas.ScreenOut])
def get_all_screens(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Screen).order_by(models.Screen.created_at.desc()).all()

@router.get("/screens/{screen_id}", response_model=schemas.ScreenOut)
def get_screen(screen_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    screen = db.query(models.Screen).filter(models.Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    return screen

@router.put("/screens/{screen_id}", response_model=schemas.ScreenOut)
def update_screen(
    screen_id: int,
    screen_data: schemas.ScreenUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin)
):
    screen = db.query(models.Screen).filter(models.Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    for key, value in screen_data.model_dump(exclude_unset=True).items():
        setattr(screen, key, value)
    db.commit()
    db.refresh(screen)
    return screen

@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(require_hr_or_admin)):
    screen = db.query(models.Screen).filter(models.Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    db.delete(screen)
    db.commit()
    return {"ok": True}

@router.post("/screens/{screen_id}/connect")
def connect_screen(screen_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(require_hr_or_admin)):
    screen = db.query(models.Screen).filter(models.Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    screen.is_connected = True
    db.commit()
    return {"ok": True, "message": f"Screen {screen.code} connected"}

@router.post("/screens/{screen_id}/disconnect")
def disconnect_screen(screen_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(require_hr_or_admin)):
    screen = db.query(models.Screen).filter(models.Screen.id == screen_id).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Screen not found")
    screen.is_connected = False
    db.commit()
    return {"ok": True}

@router.get("/screens/generate-code", dependencies=[])
def generate_code(db: Session = Depends(get_db)):
    existing_codes = [s[0] for s in db.query(models.Screen.code).all()]
    for _ in range(100):
        code = f"{random.randint(0, 999):03d}"
        if code not in existing_codes:
            return {"code": code}
    raise HTTPException(status_code=500, detail="No free codes available")

@router.get("/screens/generate-code")
def generate_code(db: Session = Depends(get_db)):
    existing_codes = [s[0] for s in db.query(models.Screen.code).all()]
    for _ in range(100):
        code = f"{random.randint(0, 999):03d}"
        if code not in existing_codes:
            return {"code": code}
    raise HTTPException(status_code=500, detail="No free codes available")

@router.post("/screens/activate")
def activate_screen(data: schemas.ScreenActivate, db: Session = Depends(get_db)):
    screen = db.query(models.Screen).filter(models.Screen.code == data.code).first()
    if not screen:
        raise HTTPException(status_code=404, detail="Code not found. Contact HR.")
    if not screen.is_connected:
        raise HTTPException(status_code=403, detail="Screen not yet connected by HR")
    screen.last_active = datetime.now()
    screen.is_online = True
    db.commit()
    return {"ok": True, "message": f"Screen {data.code} activated", "screen_id": screen.id}

@router.post("/screens/heartbeat")
def heartbeat(data: dict, db: Session = Depends(get_db)):
    screen = db.query(models.Screen).filter(models.Screen.code == data.get("code")).first()
    if screen:
        screen.last_active = datetime.now()
        screen.is_online = True
        db.commit()
    return {"ok": True}