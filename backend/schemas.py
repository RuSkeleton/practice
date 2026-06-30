from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any

class UserCreate(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    class Config:
        from_attributes = True

class SlideBase(BaseModel):
    type: str
    title: Optional[str] = None
    content: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    start_date: datetime
    end_date: datetime
    priority: int = 0
    is_auto_generated: bool = False

class SlideCreate(SlideBase):
    pass

class SlideUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None

class SlideOut(SlideBase):
    id: int
    views: int
    is_active: bool
    is_auto_generated: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    class Config:
        from_attributes = True

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