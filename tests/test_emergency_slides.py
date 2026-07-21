"""Проверки минимального режима экстренного показа."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import crud, models, schemas
from backend.database import Base
from backend.routers.screens import (
    _get_emergency_slides,
    _serialize_emergency_queue,
    get_screen_schedule,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _slide_payload(now: datetime, **overrides):
    data = {
        "name": "Слайд",
        "start_date": now - timedelta(minutes=5),
        "end_date": now + timedelta(hours=1),
        "is_active": True,
        "duration_slots": 1,
        "frequency_mode": 1,
        "hard_interval": None,
        "is_emergency": False,
        "background": {"type": "color", "value": "#000000"},
        "elements": [],
    }
    data.update(overrides)
    return schemas.SlideCreate(**data)


def test_emergency_slide_ignores_normal_frequency_settings() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _session()
    try:
        slide = crud.create_slide(
            db,
            _slide_payload(
                now,
                is_emergency=True,
                duration_slots=4,
                frequency_mode=4,
                hard_interval=7,
            ),
        )

        assert slide.duration_slots == 1
        assert slide.frequency_mode == 1
        assert slide.hard_interval is None
    finally:
        db.close()



def test_updating_slide_to_emergency_resets_normal_frequency() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _session()
    try:
        slide = crud.create_slide(
            db,
            _slide_payload(
                now,
                duration_slots=3,
                frequency_mode=4,
                hard_interval=6,
            ),
        )

        updated = crud.update_slide(
            db,
            slide.id,
            schemas.SlideUpdate(is_emergency=True, alarm_type="fire"),
        )

        assert updated is not None
        assert updated.is_emergency is True
        assert updated.duration_slots == 1
        assert updated.frequency_mode == 1
        assert updated.hard_interval is None
    finally:
        db.close()

def test_emergency_queue_contains_each_enabled_slide_once() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _session()
    try:
        current = crud.create_slide(
            db,
            _slide_payload(now, name="Текущий", is_emergency=True),
        )
        future = crud.create_slide(
            db,
            _slide_payload(
                now,
                name="Будущий",
                is_emergency=True,
                start_date=now + timedelta(minutes=10),
                end_date=now + timedelta(hours=2),
            ),
        )
        crud.create_slide(
            db,
            _slide_payload(
                now,
                name="Истёкший",
                is_emergency=True,
                start_date=now - timedelta(hours=2),
                end_date=now - timedelta(hours=1),
            ),
        )
        crud.create_slide(
            db,
            _slide_payload(now, name="Обычный", is_emergency=False),
        )

        emergency_slides = _get_emergency_slides(db, now)
        payload = _serialize_emergency_queue(emergency_slides, now)

        assert payload["active"] is True
        assert payload["queue"] == [current.id, future.id]
        assert len(payload["queue"]) == len(set(payload["queue"]))
    finally:
        db.close()


def test_future_emergency_queue_is_prefetched_but_not_active_yet() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _session()
    try:
        future = crud.create_slide(
            db,
            _slide_payload(
                now,
                is_emergency=True,
                start_date=now + timedelta(minutes=10),
                end_date=now + timedelta(hours=1),
            ),
        )

        payload = _serialize_emergency_queue(
            _get_emergency_slides(db, now),
            now,
        )

        assert payload["active"] is False
        assert payload["queue"] == [future.id]
    finally:
        db.close()

def test_screen_schedule_response_contains_emergency_queue() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _session()
    try:
        screen = models.Screen(
            code="123456",
            name="Тестовый экран",
            is_connected=True,
        )
        db.add(screen)
        db.flush()

        emergency = crud.create_slide(
            db,
            _slide_payload(now, is_emergency=True, alarm_type="fire"),
        )
        normal = crud.create_slide(
            db,
            _slide_payload(now, name="Обычный"),
        )
        db.add(
            models.ScheduleWindow(
                window_start=now - timedelta(minutes=30),
                window_end=now + timedelta(minutes=30),
                slot_duration=15,
                window_size_seconds=3600,
                queue=[normal.id],
            )
        )
        db.commit()

        response = get_screen_schedule(
            code=screen.code,
            mode="full",
            days=3,
            from_=None,
            to_=None,
            base_version=None,
            db=db,
            screen=screen,
        )

        assert response["emergency"] == {
            "active": True,
            "slot_duration": 15,
            "queue": [emergency.id],
        }
        assert response["schedule"][0]["queue"] == [normal.id]
    finally:
        db.close()

