from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON
from sqlalchemy.sql import func
from backend.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="hr")
    created_at = Column(DateTime, server_default=func.now())

class Slide(Base):
    __tablename__ = "slides"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), nullable=False)
    title = Column(String(200))
    content = Column(Text)
    extra_data = Column(JSON)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    priority = Column(Integer, default=0)
    views = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_auto_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class Screen(Base):
    __tablename__ = "screens"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(3), unique=True, nullable=False)
    name = Column(String(100), nullable=True)
    location = Column(String(200), nullable=True)
    is_connected = Column(Boolean, default=False)
    is_online = Column(Boolean, default=False)
    last_active = Column(DateTime, onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())