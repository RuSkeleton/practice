"""Встроенные аварийные пресеты и операции быстрого запуска.

Аварийные пресеты хранятся в таблице ``slides``, но не являются обычными
слайдами каталога. При первом запуске недостающие встроенные пресеты создаются
автоматически в выключенном состоянии. Их содержимое можно редактировать через
обычный редактор, а включение и выключение выполняется отдельными действиями.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend import models


EMERGENCY_PRESET_PREFIX = "emergency-preset:"
EMERGENCY_ACTIVE_HORIZON_DAYS = 3650


def _text_element(
    element_id: str,
    value: str,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    font_size: int,
    font_weight: int,
    color: str = "#ffffff",
) -> dict[str, Any]:
    return {
        "id": element_id,
        "type": "text",
        "role": "title" if element_id.endswith("title") else "body",
        "value": value,
        "layout": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "fontSize": font_size,
            "fontWeight": font_weight,
            "color": color,
            "textAlign": "center",
            "verticalAlign": "middle",
            "zIndex": 2,
        },
    }


def _preset(
    alarm_type: str,
    name: str,
    instruction: str,
    *,
    background: str = "#9d1111",
) -> dict[str, Any]:
    return {
        "alarm_type": alarm_type,
        "template_key": EMERGENCY_PRESET_PREFIX + alarm_type,
        "name": name,
        "background": {"type": "color", "value": background},
        "elements": [
            _text_element(
                f"emergency-{alarm_type}-title",
                name.upper(),
                x=160,
                y=230,
                width=1600,
                height=220,
                font_size=96,
                font_weight=900,
            ),
            _text_element(
                f"emergency-{alarm_type}-body",
                instruction,
                x=220,
                y=500,
                width=1480,
                height=280,
                font_size=48,
                font_weight=600,
                color="#fff4f4",
            ),
        ],
    }


DEFAULT_EMERGENCY_PRESETS: tuple[dict[str, Any], ...] = (
    _preset(
        "fire",
        "Пожарная тревога",
        "Сохраняйте спокойствие. Покиньте здание по ближайшему безопасному эвакуационному выходу.",
    ),
    _preset(
        "smoke",
        "Задымление",
        "Не пользуйтесь лифтом. Двигайтесь к ближайшему безопасному выходу, защищая органы дыхания.",
        background="#7f1d1d",
    ),
    _preset(
        "uav_attack",
        "Опасность атаки БПЛА",
        "Отойдите от окон и наружных стен. Перейдите в безопасное помещение и следуйте указаниям ответственных лиц.",
        background="#7a1717",
    ),
    _preset(
        "missile_alert",
        "Ракетная опасность",
        "Немедленно проследуйте в укрытие. Не задерживайтесь у окон и стеклянных перегородок.",
        background="#8f1010",
    ),
    _preset(
        "evacuation",
        "Эвакуация",
        "Организованно покиньте помещение по указанным маршрутам. Помогите людям, которым требуется сопровождение.",
        background="#a11a0a",
    ),
    _preset(
        "chemical_hazard",
        "Химическая опасность",
        "Закройте окна и двери, отключите вентиляцию и ожидайте дальнейших инструкций ответственных служб.",
        background="#6d1616",
    ),
)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_default_emergency_presets(db: Session) -> list[models.Slide]:
    """Создаёт недостающие встроенные пресеты, не изменяя существующие."""
    now = utc_now_naive()
    existing = (
        db.query(models.Slide)
        .filter(models.Slide.is_emergency.is_(True))
        .order_by(models.Slide.id.asc())
        .all()
    )
    by_template_key = {
        slide.template_key: slide
        for slide in existing
        if slide.template_key
    }
    by_alarm_type = {
        slide.alarm_type: slide
        for slide in existing
        if slide.alarm_type
    }

    changed = False
    result: list[models.Slide] = []
    for preset in DEFAULT_EMERGENCY_PRESETS:
        slide = by_template_key.get(preset["template_key"])
        if slide is None:
            slide = by_alarm_type.get(preset["alarm_type"])
            if slide is not None and not slide.template_key:
                slide.template_key = preset["template_key"]
                changed = True

        if slide is None:
            slide = models.Slide(
                name=preset["name"],
                template_key=preset["template_key"],
                kind="announcement",
                revision=1,
                start_date=now,
                end_date=now + timedelta(days=EMERGENCY_ACTIVE_HORIZON_DAYS),
                is_active=False,
                duration_slots=1,
                frequency_mode=1,
                hard_interval=None,
                is_emergency=True,
                alarm_type=preset["alarm_type"],
                background=preset["background"],
                elements=preset["elements"],
            )
            db.add(slide)
            changed = True

        result.append(slide)

    if changed:
        db.commit()
        for slide in result:
            db.refresh(slide)

    return result


def get_emergency_presets(db: Session) -> list[models.Slide]:
    return (
        db.query(models.Slide)
        .filter(models.Slide.is_emergency.is_(True))
        .order_by(models.Slide.id.asc())
        .all()
    )


def get_emergency_preset(db: Session, slide_id: int) -> models.Slide | None:
    return (
        db.query(models.Slide)
        .filter(
            models.Slide.id == slide_id,
            models.Slide.is_emergency.is_(True),
        )
        .first()
    )


def set_emergency_preset_active(
    db: Session,
    slide_id: int,
    *,
    is_active: bool,
    user_id: int | None,
) -> models.Slide | None:
    slide = get_emergency_preset(db, slide_id)
    if slide is None:
        return None

    now = utc_now_naive()
    slide.is_active = is_active
    if is_active:
        slide.start_date = now
        slide.end_date = now + timedelta(days=EMERGENCY_ACTIVE_HORIZON_DAYS)
    slide.duration_slots = 1
    slide.frequency_mode = 1
    slide.hard_interval = None
    slide.revision = int(slide.revision or 0) + 1
    slide.updated_by = user_id
    db.commit()
    db.refresh(slide)
    return slide
