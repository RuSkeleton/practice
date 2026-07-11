"""Pydantic-схемы внешнего API.

Схемы валидируют форму входных данных до того, как они попадут в SQLAlchemy.
Бизнес-проверки, которым нужна база данных (уникальность логина, последний admin),
выполняются в router/crud слоях.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


UserRole = Literal["admin", "hr", "viewer"]


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    expires_in: int


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)


class PublicConfigOut(BaseModel):
    """Только безопасные настройки, которые разрешено читать без JWT."""

    dev_mode: bool
    show_dev_login_hints: bool
    dev_username: str | None = None
    dev_password: str | None = None


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------

class UserBase(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    full_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    role: UserRole = "hr"

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Логин не может состоять из пробелов")
        if any(char.isspace() for char in value):
            raise ValueError("Логин не должен содержать пробелы")
        return value

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UserCreate(UserBase):
    password: str = Field(..., min_length=1, max_length=128)


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=2, max_length=50)
    full_name: str | None = Field(None, max_length=100)
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("Некорректный логин")
        return value

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None
    last_login: datetime | None = None


# ---------------------------------------------------------------------------
# Слайды
# ---------------------------------------------------------------------------

class SlideBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    template_key: str | None = Field(None, max_length=100)
    kind: str = Field("announcement", max_length=50)
    start_date: datetime
    end_date: datetime
    is_active: bool = True
    duration_slots: int = Field(1, ge=1, le=4)
    frequency_mode: int = Field(1, ge=1, le=4)
    hard_interval: int | None = Field(None, gt=1)
    is_emergency: bool = False
    alarm_type: str | None = Field(None, max_length=50)
    background: dict[str, Any] = Field(
        default_factory=lambda: {"type": "gradient", "value": "default"}
    )
    elements: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_period_and_frequency(self) -> "SlideBase":
        if self.end_date <= self.start_date:
            raise ValueError("Дата окончания должна быть позже даты начала")
        if self.frequency_mode == 4 and self.hard_interval is None:
            raise ValueError("Для жёсткого режима требуется hard_interval")
        if self.frequency_mode != 4 and self.hard_interval is not None:
            raise ValueError("hard_interval разрешён только для frequency_mode=4")
        return self


class SlideCreate(SlideBase):
    pass


class SlideUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    template_key: str | None = Field(None, max_length=100)
    kind: str | None = Field(None, max_length=50)
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_active: bool | None = None
    duration_slots: int | None = Field(None, ge=1, le=4)
    frequency_mode: int | None = Field(None, ge=1, le=4)
    hard_interval: int | None = Field(None, gt=1)
    is_emergency: bool | None = None
    alarm_type: str | None = Field(None, max_length=50)
    background: dict[str, Any] | None = None
    elements: list[dict[str, Any]] | None = None


class SlideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    template_key: str | None
    kind: str
    revision: int
    start_date: datetime
    end_date: datetime
    is_active: bool
    duration_slots: int
    frequency_mode: int
    hard_interval: int | None
    is_emergency: bool
    alarm_type: str | None
    background: dict[str, Any]
    elements: list[dict[str, Any]]
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime | None


# ---------------------------------------------------------------------------
# Экраны
# ---------------------------------------------------------------------------

class ScreenCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=3, pattern=r"^[0-9]{3}$")
    name: str | None = Field(None, max_length=100)
    location: str | None = Field(None, max_length=200)


class ScreenUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    location: str | None = Field(None, max_length=200)
    is_connected: bool | None = None


class ScreenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str | None
    location: str | None
    is_connected: bool
    is_online: bool
    last_active: datetime | None
    created_at: datetime


class ScreenActivate(BaseModel):
    code: str = Field(..., min_length=3, max_length=3, pattern=r"^[0-9]{3}$")
