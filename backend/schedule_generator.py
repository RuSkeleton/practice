# backend/schedule_generator.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, cast

from sqlalchemy.orm import Session

from backend.models import Slide, ScheduleWindow, SystemSetting


FALLBACK_SLIDE_ID = 0

SOFT_NORMAL = 1
SOFT_OFTEN = 2
SOFT_VERY_OFTEN = 3
HARD_INTERVAL = 4

SCHEDULE_VERSION_KEY = "schedule_version"

@dataclass(frozen=True)
class GeneratedWindow:
    window_start: datetime
    window_end: datetime
    slot_duration: int
    window_size_seconds: int
    queue: list[int]


@dataclass(frozen=True)
class ScheduleGenerationResult:
    schedule_version: int
    range_from: datetime
    range_to: datetime
    windows_count: int


class ScheduleGenerator:
    """
    Генератор обычного расписания.

    Не обрабатывает emergency-слайды.
    Не получает список слайдов извне.
    Для каждого окна сам достаёт из БД активные слайды этого окна.
    """

    def __init__(self, db: Session):
        self.db = db

    def generate_schedule(
            self,
            window_size_seconds: int,
            slot_duration_seconds: int,
            range_from: datetime,
            range_to: datetime,
    ) -> ScheduleGenerationResult:
        if window_size_seconds <= 0:
            raise ValueError("window_size_seconds must be > 0")

        if slot_duration_seconds <= 0:
            raise ValueError("slot_duration_seconds must be > 0")

        if range_to <= range_from:
            raise ValueError("range_to must be greater than range_from")

        generated_windows: list[GeneratedWindow] = []

        current_start = range_from

        while current_start < range_to:
            current_end = min(
                current_start + timedelta(seconds=window_size_seconds),
                range_to,
            )

            window = self._generate_one_window(
                window_start=current_start,
                window_end=current_end,
                slot_duration_seconds=slot_duration_seconds,
                nominal_window_size_seconds=window_size_seconds,
            )

            generated_windows.append(window)
            current_start = current_end

        try:
            self._delete_windows_in_range(range_from, range_to)

            for window in generated_windows:
                self.db.add(
                    ScheduleWindow(
                        window_start=window.window_start,
                        window_end=window.window_end,
                        slot_duration=window.slot_duration,
                        window_size_seconds=window.window_size_seconds,
                        queue=window.queue,
                    )
                )

            schedule_version = self._increment_schedule_version()
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return ScheduleGenerationResult(
            schedule_version=schedule_version,
            range_from=range_from,
            range_to=range_to,
            windows_count=len(generated_windows),
        )

    def _generate_one_window(
        self,
        window_start: datetime,
        window_end: datetime,
        slot_duration_seconds: int,
        nominal_window_size_seconds: int,
    ) -> GeneratedWindow:
        active_slides = self._get_active_slides_for_window(window_start, window_end)

        hard_slides = [
            slide for slide in active_slides
            if slide.frequency_mode == HARD_INTERVAL
        ]

        soft_slides = [
            slide for slide in active_slides
            if slide.frequency_mode in (SOFT_NORMAL, SOFT_OFTEN, SOFT_VERY_OFTEN)
        ]

        actual_window_seconds = int((window_end - window_start).total_seconds())
        capacity_slots = actual_window_seconds // slot_duration_seconds

        requires_full_queue = self._window_has_internal_time_boundaries(
            slides=active_slides,
            window_start=window_start,
            window_end=window_end,
        )

        queue: list[int] = []

        used_slots = 0

        # Логическая позиция появления слайда.
        # Не равна индексу в queue.
        position = 1

        # Позиция только среди soft-показов.
        soft_position = 1

        # Сколько раз каждый soft-слайд уже был выбран в этом окне.
        soft_shown_count: dict[int, int] = {
            slide.id: 0 for slide in soft_slides
        }

        while used_slots < capacity_slots:
            remaining_slots = capacity_slots - used_slots

            slot_start = None
            if requires_full_queue:
                slot_start = window_start + timedelta(
                    seconds=used_slots * slot_duration_seconds
                )

            selected = self._choose_hard_slide(
                hard_slides=hard_slides,
                position=position,
                remaining_slots=remaining_slots,
                slot_start=slot_start,
                slot_duration_seconds=slot_duration_seconds,
            )

            if selected is None:
                selected = self._choose_soft_slide(
                    soft_slides=soft_slides,
                    soft_shown_count=soft_shown_count,
                    soft_position=soft_position,
                    remaining_slots=remaining_slots,
                    slot_start=slot_start,
                    slot_duration_seconds=slot_duration_seconds,
                )

                if selected is not None:
                    soft_shown_count[selected.id] += 1
                    soft_position += 1

            if selected is None:
                if requires_full_queue:
                    queue.append(FALLBACK_SLIDE_ID)
                    used_slots += 1
                    position += 1
                    continue

                break

            duration = selected.duration_slots

            if duration > remaining_slots:
                break

            queue.extend([selected.id] * duration)

            used_slots += duration
            position += 1

        return GeneratedWindow(
            window_start=window_start,
            window_end=window_end,
            slot_duration=slot_duration_seconds,
            window_size_seconds=nominal_window_size_seconds,
            queue=queue,
        )

    def _get_active_slides_for_window(
            self,
            window_start: datetime,
            window_end: datetime,
    ) -> list[Slide]:
        result = (
            self.db.query(Slide)
            .filter(
                Slide.is_active.is_(True),
                Slide.is_emergency.is_(False),
                Slide.start_date < window_end,
                Slide.end_date > window_start,
            )
            .order_by(Slide.id.asc())
            .all()
        )

        return cast(list[Slide], result)

    def _window_has_internal_time_boundaries(
            self,
            slides: list[Slide],
            window_start: datetime,
            window_end: datetime,
    ) -> bool:
        for slide in slides:
            if window_start < slide.start_date < window_end:
                return True

            if window_start < slide.end_date < window_end:
                return True

        return False

    def _slide_fits_slot_time(
            self,
            slide: Slide,
            slot_start: Optional[datetime],
            slot_duration_seconds: int,
    ) -> bool:
        if slot_start is None:
            return True

        for offset in range(slide.duration_slots):
            check_time = slot_start + timedelta(
                seconds=offset * slot_duration_seconds
            )

            if not (slide.start_date <= check_time < slide.end_date):
                return False

        return True

    def _choose_hard_slide(
            self,
            hard_slides: list[Slide],
            position: int,
            remaining_slots: int,
            slot_start: Optional[datetime],
            slot_duration_seconds: int,
    ) -> Optional[Slide]:
        candidates: list[Slide] = []

        for slide in hard_slides:
            interval = slide.hard_interval

            if interval is None or interval <= 1:
                continue

            if position % interval != 0:
                continue

            if slide.duration_slots > remaining_slots:
                continue

            if not self._slide_fits_slot_time(
                    slide=slide,
                    slot_start=slot_start,
                    slot_duration_seconds=slot_duration_seconds,
            ):
                continue

            candidates.append(slide)

        if not candidates:
            return None

        # Если совпали разные hard_interval, побеждает больший N.
        # Одинаковые hard_interval на пересекающемся времени должны быть запрещены
        # ещё при создании/редактировании слайда.
        return max(
            candidates,
            key=lambda slide: (slide.hard_interval or 0, slide.id),
        )

    def _choose_soft_slide(
            self,
            soft_slides: list[Slide],
            soft_shown_count: dict[int, int],
            soft_position: int,
            remaining_slots: int,
            slot_start: Optional[datetime],
            slot_duration_seconds: int,
    ) -> Optional[Slide]:
        fitting_slides = [
            slide for slide in soft_slides
            if slide.duration_slots <= remaining_slots
               and self._slide_fits_slot_time(
                slide=slide,
                slot_start=slot_start,
                slot_duration_seconds=slot_duration_seconds,
            )
        ]

        if not fitting_slides:
            return None

        total_weight = sum(slide.frequency_mode for slide in soft_slides)

        if total_weight <= 0:
            return fitting_slides[0]

        def score(slide: Slide) -> tuple[float, int, int]:
            weight = slide.frequency_mode
            shown = soft_shown_count.get(slide.id, 0)

            # Ожидаемое количество появлений к текущему soft-шагу.
            expected = (soft_position * weight) / total_weight

            # Чем больше deficit, тем сильнее слайд "недополучил" показов.
            deficit = expected - shown

            return (
                deficit,
                -shown,
                -slide.id,
            )

        return max(fitting_slides, key=score)

    def _delete_windows_in_range(
        self,
        range_from: datetime,
        range_to: datetime,
    ) -> None:
        (
            self.db.query(ScheduleWindow)
            .filter(
                ScheduleWindow.window_start < range_to,
                ScheduleWindow.window_end > range_from,
            )
            .delete(synchronize_session=False)
        )

    def _get_schedule_version(self) -> int:
        setting = (
            self.db.query(SystemSetting)
            .filter(SystemSetting.setting_key == SCHEDULE_VERSION_KEY)
            .one_or_none()
        )

        if setting is None:
            setting = SystemSetting(
                setting_key=SCHEDULE_VERSION_KEY,
                int_value=0,
            )
            self.db.add(setting)
            self.db.flush()
            return 0

        return int(setting.int_value or 0)

    def _increment_schedule_version(self) -> int:
        setting = (
            self.db.query(SystemSetting)
            .filter(SystemSetting.setting_key == SCHEDULE_VERSION_KEY)
            .one_or_none()
        )

        if setting is None:
            setting = SystemSetting(
                setting_key=SCHEDULE_VERSION_KEY,
                int_value=1,
            )
            self.db.add(setting)
            self.db.flush()
            return 1

        new_version = int(setting.int_value or 0) + 1
        setting.int_value = new_version
        self.db.flush()
        return new_version