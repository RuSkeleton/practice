"""REST-протокол экранного клиента.

Публичным остаётся только POST /screens/activate: он одноразово обменивает
короткоживущий pairing code на случайный device token. Все остальные маршруты
требуют заголовок X-Screen-Token и получают экран из проверенного токена, а не
из присланного клиентом кода.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import config
from backend.database import get_db
from backend.models import ScheduleWindow, Screen, Slide, SystemSetting
from backend.rate_limit import SlidingWindowRateLimiter
from backend.screen_auth import issue_screen_token, require_screen, utc_now_naive


router = APIRouter()

SCHEDULE_VERSION_KEY = "schedule_version"
FALLBACK_SLIDE_ID = 0
DEFAULT_WINDOW_SIZE_SECONDS = 3600
EMERGENCY_SLOT_DURATION_SECONDS = 15

_activation_limiter = SlidingWindowRateLimiter(
    max_attempts=config.SCREEN_ACTIVATION_MAX_FAILED_ATTEMPTS_PER_IP,
    window_seconds=config.SCREEN_ACTIVATION_RATE_LIMIT_WINDOW_SECONDS,
)


class ScreenActivateRequest(BaseModel):
    code: str = Field(
        ...,
        min_length=config.SCREEN_PAIRING_CODE_LENGTH,
        max_length=config.SCREEN_PAIRING_CODE_LENGTH,
        pattern=rf"^[0-9]{{{config.SCREEN_PAIRING_CODE_LENGTH}}}$",
    )


class SlidesBatchRequest(BaseModel):
    ids: list[int | str] = Field(default_factory=list, max_length=500)


def _utc_now() -> datetime:
    return utc_now_naive()


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
        "is_emergency": bool(slide.is_emergency),
        "alarm_type": slide.alarm_type,
        "background": slide.background or {
            "type": "gradient",
            "value": "default",
        },
        "elements": slide.elements or [],
    }


def _get_emergency_slides(db: Session, now: datetime) -> list[Slide]:
    """Возвращает включённые экстренные слайды, которые ещё не завершились.

    Будущие слайды тоже попадают в ответ: экран заранее кэширует их и сам
    включает в момент start_date, в том числе при временной потере сети.
    """
    return (
        db.query(Slide)
        .filter(
            Slide.is_emergency.is_(True),
            Slide.is_active.is_(True),
            Slide.end_date > now,
        )
        .order_by(Slide.id.asc())
        .all()
    )


def _serialize_emergency_queue(
    slides: list[Slide],
    now: datetime,
) -> dict[str, Any]:
    queue = [int(slide.id) for slide in slides]
    active = any(
        slide.start_date <= now < slide.end_date
        for slide in slides
    )
    return {
        "active": active,
        "slot_duration": EMERGENCY_SLOT_DURATION_SECONDS,
        # Каждый id присутствует ровно один раз: экстренные слайды равноправны.
        "queue": queue,
    }


def _get_windows(
    db: Session,
    range_from: datetime,
    range_to: datetime,
) -> list[ScheduleWindow]:
    return (
        db.query(ScheduleWindow)
        .filter(
            ScheduleWindow.window_start < range_to,
            ScheduleWindow.window_end > range_from,
        )
        .order_by(ScheduleWindow.window_start.asc())
        .all()
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _raise_if_activation_limited(ip_key: str) -> None:
    state = _activation_limiter.check(ip_key)
    if state.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Слишком много попыток привязки. Повторите позже",
        headers={"Retry-After": str(state.retry_after_seconds)},
    )


def _invalid_pairing_response() -> HTTPException:
    # Один ответ для отсутствующего, просроченного, уже использованного и
    # отключённого кода не позволяет перечислять состояние экранов.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Код привязки недействителен или истёк",
    )


@router.post("/screens/activate")
def activate_screen(
    payload: ScreenActivateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ip_key = _client_ip(request)
    _raise_if_activation_limited(ip_key)

    screen = (
        db.query(Screen)
        .filter(Screen.code == payload.code)
        .one_or_none()
    )
    if screen is None:
        _activation_limiter.record_failure(ip_key)
        raise _invalid_pairing_response()

    try:
        raw_token = issue_screen_token(db, screen)
    except ValueError:
        _activation_limiter.record_failure(ip_key)
        raise _invalid_pairing_response()

    _activation_limiter.reset(ip_key)
    return {
        "ok": True,
        "screen": _screen_payload(screen),
        "screen_token": raw_token,
        "token_type": "screen",
        "server_time": _iso_z(_utc_now()),
    }


@router.get("/screen/me")
def get_current_screen_info(
    screen: Screen = Depends(require_screen),
) -> dict[str, Any]:
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
    screen: Screen = Depends(require_screen),
) -> dict[str, Any]:
    if code != screen.code:
        raise HTTPException(status_code=403, detail="Токен принадлежит другому экрану")

    now = _utc_now()
    current_version = _get_schedule_version(db)

    if mode == "full":
        range_from = now
        range_to = now + timedelta(days=days)
    else:
        if from_ is None or to_ is None:
            raise HTTPException(
                status_code=400,
                detail="Patch schedule requires from and to",
            )
        range_from = _to_db_datetime(from_)
        range_to = _to_db_datetime(to_)
        if range_to <= range_from:
            raise HTTPException(
                status_code=400,
                detail="Patch to must be greater than from",
            )

    windows = _get_windows(db, range_from, range_to)
    emergency_slides = _get_emergency_slides(db, now)
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
        "emergency": _serialize_emergency_queue(emergency_slides, now),
        "schedule": [_serialize_window(window) for window in windows],
    }

    if mode == "full":
        response.update(
            {
                "valid_from": _iso_z(range_from),
                "valid_to": _iso_z(range_to),
            }
        )
    else:
        previous_version = current_version - 1 if current_version > 0 else 0
        if base_version is not None and base_version == previous_version:
            previous_version = base_version

        response.update(
            {
                "previous_schedule_version": previous_version,
                "patch_from": _iso_z(range_from),
                "patch_to": _iso_z(range_to),
            }
        )

    return response


@router.post("/slides/batch")
def get_slides_batch(
    payload: SlidesBatchRequest,
    db: Session = Depends(get_db),
    _: Screen = Depends(require_screen),
) -> dict[str, Any]:
    requested_ids: list[int] = []
    for raw_id in payload.ids:
        try:
            slide_id = int(raw_id)
        except (TypeError, ValueError):
            continue

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
        "slides": [
            _serialize_slide(slides_by_id[slide_id])
            for slide_id in requested_ids
            if slide_id in slides_by_id
        ],
        "missing_ids": [
            str(slide_id)
            for slide_id in requested_ids
            if slide_id not in slides_by_id
        ],
        "server_time": _iso_z(_utc_now()),
    }
