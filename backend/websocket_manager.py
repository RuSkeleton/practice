"""Совместимый импорт старого websocket_manager без публичного legacy-route.

Ранее этот модуль объявлял неаутентифицированный ``/ws/slides``. Текущий сервер
использует только защищённый ``/ws/screens`` из backend.routers.websocket.
Оставлен лишь адаптер уведомлений для старых импортов.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.routers.websocket import manager


# Намеренно пустой router: legacy /ws/slides удалён из поверхности атаки.
router = APIRouter()


async def notify_clients(message: dict) -> None:
    await manager.broadcast(message)
