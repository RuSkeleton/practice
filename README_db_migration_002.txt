Что делает upgrade:
1. Заменяет старую таблицу slides(type/title/content/extra_data/priority/views) на контрактную slides:
   name, template_key, kind, revision, start_date, end_date, is_active,
   duration_slots, frequency_mode, hard_interval, is_emergency, alarm_type,
   background, elements, created_by, updated_by, created_at, updated_at.
2. Сохраняет старые слайды, конвертируя их в background + elements.
3. Маппит старый priority в frequency_mode:
   priority <= 0 -> 1,
   priority == 1 -> 2,
   priority >= 2 -> 3.
4. Создаёт schedule_windows.
5. Создаёт system_settings.
6. Добавляет system_settings.schedule_version = 0.

Команда запуска из корня проекта:
cd "F:\team 2"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
