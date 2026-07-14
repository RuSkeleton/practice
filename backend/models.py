
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean,
    JSON,
    ForeignKey,
    CheckConstraint,
    Index,
)
from sqlalchemy.sql import func
from backend.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="hr")          # hr, admin, viewer
    full_name = Column(String(100), nullable=True)   # ФИО
    email = Column(String(100), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    # Версия сессии. Увеличивается при смене пароля и немедленно отзывает
    # все JWT, выданные до изменения учётных данных.
    auth_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    last_login = Column(DateTime, nullable=True)

class Slide(Base):
    __tablename__ = "slides"

    id = Column(Integer, primary_key=True, index=True)

    # Внутренние поля для админки
    name = Column(String(200), nullable=False)
    template_key = Column(String(100), nullable=True)
    kind = Column(String(50), nullable=False, default="announcement")
    revision = Column(Integer, nullable=False, default=1)

    # Период показа
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # Управление показом
    duration_slots = Column(Integer, nullable=False, default=1)

    # 1 = soft_normal
    # 2 = soft_often
    # 3 = soft_very_often
    # 4 = hard_interval
    frequency_mode = Column(Integer, nullable=False, default=1)

    # NULL для soft-режимов, > 1 для hard_interval
    hard_interval = Column(Integer, nullable=True)

    # Экстренные слайды не участвуют в обычном генераторе
    is_emergency = Column(Boolean, nullable=False, default=False)
    alarm_type = Column(String(50), nullable=True)

    # То, что реально уходит экранному клиенту
    background = Column(JSON, nullable=False, default=dict)
    elements = Column(JSON, nullable=False, default=list)

    # Служебное
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "duration_slots >= 1 AND duration_slots <= 4",
            name="ck_slides_duration_slots_range",
        ),
        CheckConstraint(
            "frequency_mode >= 1 AND frequency_mode <= 4",
            name="ck_slides_frequency_mode_range",
        ),
        CheckConstraint(
            "(frequency_mode != 4 AND hard_interval IS NULL) OR "
            "(frequency_mode = 4 AND hard_interval > 1)",
            name="ck_slides_hard_interval_consistency",
        ),
        Index("ix_slides_active_period", "is_active", "start_date", "end_date"),
        Index("ix_slides_hard_interval", "frequency_mode", "hard_interval"),
        Index("ix_slides_emergency", "is_emergency", "alarm_type"),
    )

class Screen(Base):
    __tablename__ = "screens"
    id = Column(Integer, primary_key=True, index=True)

    # Короткоживущий одноразовый код привязки. После активации он больше не
    # подтверждает экран: постоянная аутентификация выполняется device token.
    code = Column(String(6), unique=True, nullable=False)
    pairing_expires_at = Column(DateTime, nullable=True)

    # Сырой device token в базе никогда не хранится.
    device_token_hash = Column(String(64), unique=True, nullable=True)
    token_created_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)

    name = Column(String(100), nullable=True)
    location = Column(String(200), nullable=True)
    is_connected = Column(Boolean, default=False)
    is_online = Column(Boolean, default=False)
    last_active = Column(DateTime, onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())

    @property
    def is_paired(self) -> bool:
        return bool(self.device_token_hash)

class ScheduleWindow(Base):
    __tablename__ = "schedule_windows"

    id = Column(Integer, primary_key=True, index=True)

    window_start = Column(DateTime, nullable=False, index=True)
    window_end = Column(DateTime, nullable=False, index=True)

    slot_duration = Column(Integer, nullable=False, default=15)
    window_size_seconds = Column(Integer, nullable=False, default=3600)

    # Массив slide_id.
    # Повтор id означает повтор физического слота показа.
    # Например: [12, 12, 15, 18]
    queue = Column(JSON, nullable=False, default=list)

    generated_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "window_end > window_start",
            name="ck_schedule_windows_valid_period",
        ),
        CheckConstraint(
            "slot_duration > 0",
            name="ck_schedule_windows_slot_duration_positive",
        ),
        CheckConstraint(
            "window_size_seconds > 0",
            name="ck_schedule_windows_window_size_positive",
        ),
    )

class SystemSetting(Base):
    __tablename__ = "system_settings"

    setting_key = Column(String(100), primary_key=True)
    int_value = Column(Integer, nullable=True)
    str_value = Column(String(100), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
