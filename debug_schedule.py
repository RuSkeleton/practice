from datetime import datetime, timedelta, timezone
from backend.database import SessionLocal
from backend.models import Slide, ScheduleWindow, SystemSetting

db = SessionLocal()
try:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    print("UTC now:", now)

    slide = db.query(Slide).order_by(Slide.id.desc()).first()
    if not slide:
        print("No slides")
        raise SystemExit

    print("Latest slide:")
    print("  id:", slide.id)
    print("  name:", slide.name)
    print("  start_date:", slide.start_date)
    print("  end_date:", slide.end_date)
    print("  is_active:", slide.is_active)
    print("  is_emergency:", slide.is_emergency)
    print("  duration_slots:", slide.duration_slots)
    print("  frequency_mode:", slide.frequency_mode)
    print("  hard_interval:", slide.hard_interval)

    active = (
        db.query(Slide)
        .filter(
            Slide.is_active.is_(True),
            Slide.is_emergency.is_(False),
            Slide.start_date < now + timedelta(days=3),
            Slide.end_date > now.replace(minute=0, second=0, microsecond=0),
        )
        .order_by(Slide.id.asc())
        .all()
    )

    print("Candidate slide ids for schedule:", [s.id for s in active])

    setting = db.query(SystemSetting).filter(SystemSetting.setting_key == "schedule_version").one_or_none()
    print("schedule_version:", setting.int_value if setting else None)

    windows = db.query(ScheduleWindow).order_by(ScheduleWindow.window_start.asc()).limit(3).all()
    print("First windows:")
    for w in windows:
        q = list(w.queue or [])
        print(" ", w.window_start, "->", w.window_end, "len:", len(q), "contains latest:", slide.id in q)
        print("   queue head:", q[:80])
finally:
    db.close()
