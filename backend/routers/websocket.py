"""WebSocket экранов с обязательной аутентификацией device token."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Screen, SystemSetting
from backend.screen_auth import get_screen_by_token


router = APIRouter()

SCHEDULE_VERSION_KEY = "schedule_version"
PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 90


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_z(value: Optional[datetime] = None) -> str:
    value = value or _utc_now()
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_schedule_version(db: Session) -> int:
    setting = (
        db.query(SystemSetting)
        .filter(SystemSetting.setting_key == SCHEDULE_VERSION_KEY)
        .one_or_none()
    )
    if setting is None or setting.int_value is None:
        return 0
    return int(setting.int_value)


class ScreenConnectionManager:
    def __init__(self) -> None:
        self._connections_by_code: dict[str, WebSocket] = {}
        self._codes_by_connection: dict[WebSocket, str] = {}

    async def register(self, screen_code: str, websocket: WebSocket) -> None:
        old_connection = self._connections_by_code.get(screen_code)
        if old_connection is not None and old_connection is not websocket:
            try:
                await old_connection.close(code=1000)
            except Exception:
                pass
            self.unregister(old_connection)

        self._connections_by_code[screen_code] = websocket
        self._codes_by_connection[websocket] = screen_code

    def unregister(self, websocket: WebSocket) -> Optional[str]:
        screen_code = self._codes_by_connection.pop(websocket, None)
        if screen_code and self._connections_by_code.get(screen_code) is websocket:
            self._connections_by_code.pop(screen_code, None)
        return screen_code

    async def send_to_screen(
        self,
        screen_code: str,
        message: dict[str, Any],
    ) -> bool:
        websocket = self._connections_by_code.get(screen_code)
        if websocket is None:
            return False
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            self.unregister(websocket)
            return False

    async def broadcast(self, message: dict[str, Any]) -> None:
        for screen_code in list(self._connections_by_code.keys()):
            await self.send_to_screen(screen_code, message)


manager = ScreenConnectionManager()


def _find_screen(db: Session, code: str) -> Optional[Screen]:
    return db.query(Screen).filter(Screen.code == code).one_or_none()


def _mark_screen_online(db: Session, screen: Screen) -> None:
    screen.is_online = True
    screen.last_active = _utc_now()
    db.commit()


def _mark_screen_offline_by_code(screen_code: Optional[str]) -> None:
    if not screen_code:
        return

    db = SessionLocal()
    try:
        screen = _find_screen(db, screen_code)
        if screen is not None:
            screen.is_online = False
            screen.last_active = _utc_now()
            db.commit()
    finally:
        db.close()


async def _send_register_failed(websocket: WebSocket, message: str) -> None:
    await websocket.send_json(
        {
            "type": "register_failed",
            "ok": False,
            "error": "screen_auth_failed",
            "message": message,
        }
    )


async def _handle_register(
    websocket: WebSocket,
    message: dict[str, Any],
) -> Optional[str]:
    screen_token = str(message.get("screen_token") or "")
    claimed_code = str(message.get("code") or "")
    cached_schedule_version = _safe_int(
        message.get("cached_schedule_version"),
        0,
    )

    db = SessionLocal()
    try:
        screen = get_screen_by_token(db, screen_token)
        if screen is None:
            await _send_register_failed(
                websocket,
                "Не удалось подтвердить экран",
            )
            return None

        if claimed_code and claimed_code != screen.code:
            await _send_register_failed(
                websocket,
                "Токен принадлежит другому экрану",
            )
            return None

        if not screen.is_connected:
            await _send_register_failed(
                websocket,
                "Экран отключён администратором",
            )
            return None

        current_schedule_version = _get_schedule_version(db)
        _mark_screen_online(db, screen)
        await manager.register(screen.code, websocket)

        await websocket.send_json(
            {
                "type": "registered",
                "ok": True,
                "screen_id": screen.id,
                "server_time": _iso_z(),
                "current_schedule_version": current_schedule_version,
                "recommended_action": (
                    "none"
                    if cached_schedule_version == current_schedule_version
                    else "full_sync"
                ),
            }
        )
        return screen.code
    finally:
        db.close()


async def _handle_pong(screen_code: Optional[str]) -> None:
    if not screen_code:
        return

    db = SessionLocal()
    try:
        screen = _find_screen(db, screen_code)
        if screen is not None and screen.is_connected:
            _mark_screen_online(db, screen)
    finally:
        db.close()


@router.websocket("/ws/screens")
async def screens_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    registered_code: Optional[str] = None
    last_seen = datetime.now(timezone.utc)

    try:
        first_message = await websocket.receive_json()
        if str(first_message.get("type") or "").lower() != "register":
            await _send_register_failed(
                websocket,
                "Первым сообщением должен быть register",
            )
            await websocket.close(code=1008)
            return

        registered_code = await _handle_register(websocket, first_message)
        if not registered_code:
            await websocket.close(code=1008)
            return

        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=PING_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "ping",
                        "server_time": _iso_z(),
                    }
                )

                age = (
                    datetime.now(timezone.utc) - last_seen
                ).total_seconds()
                if age > PING_TIMEOUT_SECONDS:
                    await websocket.close(code=1001)
                    return
                continue

            last_seen = datetime.now(timezone.utc)
            message_type = str(message.get("type") or "").lower()

            if message_type == "pong":
                await _handle_pong(registered_code)
            elif message_type == "register":
                registered_code = await _handle_register(websocket, message)
                if not registered_code:
                    await websocket.close(code=1008)
                    return

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        disconnected_code = manager.unregister(websocket) or registered_code
        _mark_screen_offline_by_code(disconnected_code)


async def notify_schedule_updated(
    *,
    mode: str = "full",
    schedule_version: int,
    previous_schedule_version: Optional[int] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    reason: str = "schedule_updated",
) -> None:
    message: dict[str, Any] = {
        "type": "schedule_updated",
        "mode": mode,
        "schedule_version": schedule_version,
        "reason": reason,
        "server_time": _iso_z(),
    }
    if previous_schedule_version is not None:
        message["previous_schedule_version"] = previous_schedule_version
    if from_ is not None:
        message["from"] = from_
    if to is not None:
        message["to"] = to
    await manager.broadcast(message)


async def notify_slides_updated(
    slide_ids: list[int | str],
    reason: str = "slide_content_updated",
) -> None:
    await manager.broadcast(
        {
            "type": "slides_updated",
            "slide_ids": [str(slide_id) for slide_id in slide_ids],
            "reason": reason,
            "server_time": _iso_z(),
        }
    )


async def notify_screen_disabled(
    screen_code: str,
    message: str = "Экран отключён администратором",
) -> None:
    await manager.send_to_screen(
        screen_code,
        {
            "type": "screen_disabled",
            "message": message,
            "server_time": _iso_z(),
        },
    )
