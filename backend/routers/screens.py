# backend/api/screens.py
# Роуты экранного клиента: активация, получение расписания, догрузка слайдов.

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ScheduleWindow, Screen, Slide, SystemSetting


router = APIRouter()

SCHEDULE_VERSION_KEY = "schedule_version"
FALLBACK_SLIDE_ID = 0
DEFAULT_WINDOW_SIZE_SECONDS = 3600


class ScreenActivateRequest(BaseModel):
    code: str = Field(..., min_length=3, max_length=3, pattern=r"^[0-9]{3}$")


class SlidesBatchRequest(BaseModel):
    ids: list[int | str] = Field(default_factory=list)


def _utc_now() -> datetime:
    # В БД пока используем naive UTC, наружу отдаём ISO с Z.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _iso_z(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


def _get_schedule_version(db: Session) -> int:
    setting = (
        db.query(SystemSetting)
        .filter(SystemSetting.setting_key == SCHEDULE_VERSION_KEY)
        .one_or_none()
    )
    if setting is None or setting.int_value is None:
        return 0
    return int(setting.int_value)


def _screen_payload(screen: Screen) -> dict[str, Any]:
    return {
        "id": screen.id,
        "code": screen.code,
        "name": screen.name or f"Экран {screen.code}",
        # В текущей модели отдельного is_enabled нет.
        # Временно считаем is_connected признаком разрешённого/подключённого экрана.
        "is_enabled": bool(screen.is_connected),
    }


def _serialize_window(window: ScheduleWindow) -> dict[str, Any]:
    return {
        "window_start": _iso_z(window.window_start),
        "window_end": _iso_z(window.window_end),
        "slot_duration": int(window.slot_duration or 15),
        "queue": list(window.queue or []),
    }


def _serialize_slide(slide: Slide) -> dict[str, Any]:
    return {
        "id": slide.id,
        "revision": int(slide.revision or 1),
        "start_date": _iso_z(slide.start_date),
        "end_date": _iso_z(slide.end_date),
        "is_active": bool(slide.is_active),
        "background": slide.background or {"type": "gradient", "value": "default"},
        "elements": slide.elements or [],
    }


def _find_screen_by_code(db: Session, code: str) -> Screen:
    screen = db.query(Screen).filter(Screen.code == code).one_or_none()
    if screen is None:
        raise HTTPException(
            status_code=404,
            detail={
                "ok": False,
                "error": "screen_not_found",
                "message": "Экран с указанным кодом не найден",
            },
        )
    return screen


def _ensure_screen_enabled(screen: Screen) -> None:
    if not screen.is_connected:
        raise HTTPException(
            status_code=403,
            detail={
                "ok": False,
                "error": "screen_disabled",
                "message": "Экран отключён или ещё не подключён администратором",
            },
        )


def _get_windows(db: Session, range_from: datetime, range_to: datetime) -> list[ScheduleWindow]:
    return (
        db.query(ScheduleWindow)
        .filter(
            ScheduleWindow.window_start < range_to,
            ScheduleWindow.window_end > range_from,
        )
        .order_by(ScheduleWindow.window_start.asc())
        .all()
    )


@router.post("/screens/activate")
def activate_screen(payload: ScreenActivateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    screen = _find_screen_by_code(db, payload.code)
    _ensure_screen_enabled(screen)

    screen.is_online = True
    screen.last_active = _utc_now()
    db.commit()

    return {
        "ok": True,
        "screen": _screen_payload(screen),
        "server_time": _iso_z(_utc_now()),
    }


@router.get("/screens/{code}/schedule")
def get_screen_schedule(
    code: str,
    mode: str = Query("full", pattern="^(full|patch)$"),
    days: int = Query(3, ge=1, le=14),
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to_: Optional[datetime] = Query(default=None, alias="to"),
    base_version: Optional[int] = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    screen = _find_screen_by_code(db, code)
    _ensure_screen_enabled(screen)

    now = _utc_now()
    current_version = _get_schedule_version(db)

    if mode == "full":
        range_from = now
        range_to = now + timedelta(days=days)
    else:
        if from_ is None or to_ is None:
            raise HTTPException(status_code=400, detail="Patch schedule requires from and to")
        range_from = _to_db_datetime(from_)
        range_to = _to_db_datetime(to_)
        if range_to <= range_from:
            raise HTTPException(status_code=400, detail="Patch to must be greater than from")

    windows = _get_windows(db, range_from, range_to)
    window_size_seconds = (
        int(windows[0].window_size_seconds)
        if windows and windows[0].window_size_seconds
        else DEFAULT_WINDOW_SIZE_SECONDS
    )

    response: dict[str, Any] = {
        "mode": mode,
        "schedule_version": current_version,
        "generated_at": _iso_z(now),
        "server_time": _iso_z(now),
        "window_size_seconds": window_size_seconds,
        "schedule": [_serialize_window(window) for window in windows],
    }

    if mode == "full":
        response.update({
            "valid_from": _iso_z(range_from),
            "valid_to": _iso_z(range_to),
        })
    else:
        # Если клиент отстал не на одну версию, он сам уйдёт в full sync,
        # потому что previous_schedule_version не совпадёт с локальной версией.
        previous_version = current_version - 1 if current_version > 0 else 0
        if base_version is not None and base_version == previous_version:
            previous_version = base_version

        response.update({
            "previous_schedule_version": previous_version,
            "patch_from": _iso_z(range_from),
            "patch_to": _iso_z(range_to),
        })

    return response


@router.post("/slides/batch")
def get_slides_batch(payload: SlidesBatchRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    requested_ids: list[int] = []
    for raw_id in payload.ids:
        try:
            slide_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        # 0 зарезервирован под локальную заглушку клиента и не ходит в БД.
        if slide_id == FALLBACK_SLIDE_ID:
            continue
        if slide_id > 0 and slide_id not in requested_ids:
            requested_ids.append(slide_id)

    if not requested_ids:
        return {
            "slides": [],
            "missing_ids": [],
            "server_time": _iso_z(_utc_now()),
        }

    slides = db.query(Slide).filter(Slide.id.in_(requested_ids)).all()
    slides_by_id = {int(slide.id): slide for slide in slides}

    return {
        "slides": [_serialize_slide(slides_by_id[slide_id]) for slide_id in requested_ids if slide_id in slides_by_id],
        "missing_ids": [str(slide_id) for slide_id in requested_ids if slide_id not in slides_by_id],
        "server_time": _iso_z(_utc_now()),
    }
