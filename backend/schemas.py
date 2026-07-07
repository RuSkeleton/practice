from __future__ import annotations
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Optional

# ----- Пользователи -----
class UserBase(BaseModel):
    username: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = "hr"

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

class UserOut(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

# ----- Слайды (новая модель) -----
class SlideBase(BaseModel):
    name: str = Field(..., max_length=200)
    template_key: Optional[str] = Field(None, max_length=100)
    kind: str = Field("announcement", max_length=50)
    start_date: datetime
    end_date: datetime
    is_active: bool = True
    duration_slots: int = Field(1, ge=1, le=4)
    frequency_mode: int = Field(1, ge=1, le=4)
    hard_interval: Optional[int] = Field(None, gt=1)
    is_emergency: bool = False
    alarm_type: Optional[str] = Field(None, max_length=50)
    background: dict[str, Any] = Field(default_factory=lambda: {"type": "gradient", "value": "default"})
    elements: list[dict[str, Any]] = Field(default_factory=list)

class SlideCreate(SlideBase):
    pass

class SlideUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    template_key: Optional[str] = Field(None, max_length=100)
    kind: Optional[str] = Field(None, max_length=50)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None
    duration_slots: Optional[int] = Field(None, ge=1, le=4)
    frequency_mode: Optional[int] = Field(None, ge=1, le=4)
    hard_interval: Optional[int] = Field(None, gt=1)
    is_emergency: Optional[bool] = None
    alarm_type: Optional[str] = Field(None, max_length=50)
    background: Optional[dict[str, Any]] = None
    elements: Optional[list[dict[str, Any]]] = None

class SlideOut(BaseModel):
    id: int
    name: str
    template_key: Optional[str]
    kind: str
    revision: int
    start_date: datetime
    end_date: datetime
    is_active: bool
    duration_slots: int
    frequency_mode: int
    hard_interval: Optional[int]
    is_emergency: bool
    alarm_type: Optional[str]
    background: dict[str, Any]
    elements: list[dict[str, Any]]
    created_by: Optional[int]
    updated_by: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

# ----- Экраны -----
class ScreenCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=3, pattern=r"^[0-9]{3}$")
    name: Optional[str] = None
    location: Optional[str] = None

class ScreenUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    is_connected: Optional[bool] = None

class ScreenOut(BaseModel):
    id: int
    code: str
    name: Optional[str]
    location: Optional[str]
    is_connected: bool
    is_online: bool
    last_active: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class ScreenActivate(BaseModel):
    code: str = Field(..., min_length=3, max_length=3, pattern=r"^[0-9]{3}$")