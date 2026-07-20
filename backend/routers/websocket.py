"""WebSocket-каналы экранов и административной панели."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend import auth
from backend.config import config
from backend.database import SessionLocal
from backend.models import Screen, SystemSetting, User
from backend.screen_auth import get_screen_by_token


router = APIRouter()

SCHEDULE_VERSION_KEY = "schedule_version"
PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 90
ADMIN_AUTH_TIMEOUT_SECONDS = 10


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


class AdminConnectionManager:
    """Хранит WebSocket-соединения авторизованных HR/admin-пользователей."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def register(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)

    def unregister(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def send(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        if websocket not in self._connections:
            return False
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            self.unregister(websocket)
            return False

    async def broadcast(self, message: dict[str, Any]) -> None:
        for websocket in list(self._connections):
            await self.send(websocket, message)


manager = ScreenConnectionManager()
admin_manager = AdminConnectionManager()


def _find_screen(db: Session, code: str) -> Optional[Screen]:
    return db.query(Screen).filter(Screen.code == code).one_or_none()


def _mark_screen_online(db: Session, screen: Screen) -> bool:
    """Помечает экран онлайн и сообщает, изменился ли сам статус."""
    became_online = not bool(screen.is_online)
    screen.is_online = True
    screen.last_active = _utc_now()
    db.commit()
    return became_online


async def _mark_screen_offline_by_code(screen_code: Optional[str]) -> None:
    """Помечает экран офлайн и уведомляет админку только при переходе статуса."""
    if not screen_code:
        return

    screen_id: Optional[int] = None
    became_offline = False

    db = SessionLocal()
    try:
        screen = _find_screen(db, screen_code)
        if screen is not None:
            screen_id = screen.id
            became_offline = bool(screen.is_online)
            screen.is_online = False
            screen.last_active = _utc_now()
            db.commit()
    finally:
        db.close()

    if became_offline and screen_id is not None:
        await notify_screens_updated([screen_id], "screen_offline")


def _authenticate_admin_access_token(token: str) -> Optional[tuple[int, str]]:
    """Проверяет тот же access JWT, который используется HTTP API.

    JWT не передаётся в URL, чтобы он не попадал в access-логи. Клиент
    отправляет его первым JSON-сообщением после установки соединения.
    """

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            config.SECRET_KEY,
            algorithms=[config.ALGORITHM],
        )
        if payload.get("type") != "access":
            return None

        user_id = int(payload.get("sub"))
        token_version = int(payload.get("ver"))
    except (JWTError, TypeError, ValueError):
        return None

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            return None
        if token_version != int(user.auth_version or 1):
            return None
        if not user.is_active:
            return None
        if user.role not in {auth.ROLE_HR, auth.ROLE_ADMIN}:
            return None
        return user.id, user.role
    finally:
        db.close()


async def _send_register_failed(
    websocket: WebSocket,
    *,
    error: str,
    message: str,
) -> None:
    """Отправляет клиенту машиночитаемую причину отказа регистрации."""
    await websocket.send_json(
        {
            "type": "register_failed",
            "ok": False,
            "error": error,
            "message": message,
            "server_time": _iso_z(),
        }
    )


async def _send_admin_auth_failed(websocket: WebSocket, message: str) -> None:
    await websocket.send_json(
        {
            "type": "auth_failed",
            "ok": False,
            "error": "admin_auth_failed",
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
                error="screen_credentials_invalid",
                message="Токен экрана недействителен или был отозван",
            )
            return None

        if claimed_code and claimed_code != screen.code:
            await _send_register_failed(
                websocket,
                error="screen_credentials_invalid",
                message="Токен принадлежит другому экрану",
            )
            return None

        if not screen.is_connected:
            await _send_register_failed(
                websocket,
                error="screen_suspended",
                message="Показ временно приостановлен администратором",
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

        # Уведомляем при каждой успешной WebSocket-регистрации. REST-запросы
        # экранного клиента тоже могут заранее выставить is_online=True,
        # поэтому проверка только перехода False -> True пропустила бы событие.
        await notify_screens_updated([screen.id], "screen_online")

        return screen.code
    finally:
        db.close()


async def _handle_pong(screen_code: Optional[str]) -> None:
    if not screen_code:
        return

    screen_id: Optional[int] = None
    became_online = False

    db = SessionLocal()
    try:
        screen = _find_screen(db, screen_code)
        if screen is not None and screen.is_connected:
            screen_id = screen.id
            became_online = _mark_screen_online(db, screen)
    finally:
        db.close()

    if became_online and screen_id is not None:
        await notify_screens_updated([screen_id], "screen_online")


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
                error="register_required",
                message="Первым сообщением должен быть register",
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
        # Если соединение было заменено новым для того же экрана, register()
        # уже удалил старый websocket из manager. В таком случае старое
        # соединение не должно помечать новый активный экран как offline.
        disconnected_code = manager.unregister(websocket)
        await _mark_screen_offline_by_code(disconnected_code)


@router.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket) -> None:
    """Push-уведомления для открытой административной панели.

    Первое сообщение должно иметь вид:
    {"type": "authenticate", "token": "<access JWT>"}
    """

    await websocket.accept()
    is_registered = False
    last_seen = datetime.now(timezone.utc)

    try:
        try:
            first_message = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=ADMIN_AUTH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await _send_admin_auth_failed(
                websocket,
                "Не получены данные авторизации",
            )
            await websocket.close(code=1008)
            return

        if str(first_message.get("type") or "").lower() != "authenticate":
            await _send_admin_auth_failed(
                websocket,
                "Первым сообщением должен быть authenticate",
            )
            await websocket.close(code=1008)
            return

        admin_token = str(first_message.get("token") or "")
        authenticated_user = _authenticate_admin_access_token(admin_token)
        if authenticated_user is None:
            await _send_admin_auth_failed(
                websocket,
                "Не удалось подтвердить учётные данные",
            )
            await websocket.close(code=1008)
            return

        user_id, role = authenticated_user
        admin_manager.register(websocket)
        is_registered = True

        await websocket.send_json(
            {
                "type": "authenticated",
                "ok": True,
                "user_id": user_id,
                "role": role,
                "server_time": _iso_z(),
            }
        )

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
                # Проверяем не только срок JWT, но и auth_version,
                # is_active и актуальную роль пользователя. Поэтому смена
                # пароля или отключение аккаунта закрывает живой WebSocket.
                if _authenticate_admin_access_token(admin_token) is None:
                    await _send_admin_auth_failed(
                        websocket,
                        "Сессия больше не действительна",
                    )
                    await websocket.close(code=1008)
                    return
                continue

    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if is_registered:
            admin_manager.unregister(websocket)


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
    message = {
        "type": "slides_updated",
        "slide_ids": [str(slide_id) for slide_id in slide_ids],
        "reason": reason,
        "server_time": _iso_z(),
    }

    # Экран получает событие и точечно догружает изменившиеся слайды.
    await manager.broadcast(message)

    # Админ-панель получает то же событие и перечитывает каталог через REST.
    await admin_manager.broadcast(message)


async def notify_screens_updated(
    screen_ids: list[int | str],
    reason: str = "screen_updated",
) -> None:
    """Сообщает административным панелям, что каталог экранов изменился."""
    await admin_manager.broadcast(
        {
            "type": "screens_updated",
            "screen_ids": [str(screen_id) for screen_id in screen_ids],
            "reason": reason,
            "server_time": _iso_z(),
        }
    )


async def notify_users_updated(
    user_ids: list[int | str],
    reason: str = "user_updated",
) -> None:
    """Сообщает административным панелям, что каталог пользователей изменился."""
    await admin_manager.broadcast(
        {
            "type": "users_updated",
            "user_ids": [str(user_id) for user_id in user_ids],
            "reason": reason,
            "server_time": _iso_z(),
        }
    )


async def notify_screen_suspended(
    screen_code: str,
    message: str = "Показ временно приостановлен администратором",
) -> None:
    """Временно останавливает показ, не отзывая device token."""
    await manager.send_to_screen(
        screen_code,
        {
            "type": "screen_suspended",
            "message": message,
            "server_time": _iso_z(),
        },
    )


async def notify_screen_resumed(
    screen_code: str,
    message: str = "Показ снова разрешён администратором",
) -> None:
    """Ускоряет восстановление, если suspend-соединение ещё не закрыто клиентом."""
    await manager.send_to_screen(
        screen_code,
        {
            "type": "screen_resumed",
            "message": message,
            "server_time": _iso_z(),
        },
    )


async def notify_screen_credentials_revoked(
    screen_code: str,
    message: str = "Привязка экрана отозвана администратором",
) -> None:
    """Сообщает клиенту, что сохранённый device token больше недействителен."""
    await manager.send_to_screen(
        screen_code,
        {
            "type": "screen_credentials_revoked",
            "message": message,
            "server_time": _iso_z(),
        },
    )


async def notify_screen_disabled(
    screen_code: str,
    message: str = "Привязка экрана отозвана администратором",
) -> None:
    """Совместимая обёртка для старых импортов.

    Обычное временное отключение должно использовать
    :func:`notify_screen_suspended`. Эта функция означает окончательный отзыв
    учётных данных устройства.
    """
    await notify_screen_credentials_revoked(screen_code, message)
