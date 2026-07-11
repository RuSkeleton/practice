"""Конфигурация приложения и проверки безопасности при запуске.

Главный принцип этого файла: опасная конфигурация должна обнаруживаться сразу,
а не после развёртывания. Поэтому production-режим не имеет запасного JWT-секрета
и не разрешает случайно включить dev-bootstrap.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# .env загружается из корня проекта, а не из текущей рабочей папки.
# Поэтому запуск из PyCharm, PowerShell и systemd будет читать один файл.
load_dotenv(BASE_DIR / ".env")


def _normalize_database_url(url: str) -> str:
    """Превращает относительный SQLite URL в абсолютный.

    Без этого ``sqlite:///./data/signage.db`` зависит от папки, из которой
    запущен Python. После нормализации база всегда находится в корне проекта.
    """
    if not url.startswith("sqlite:///") or url.startswith("sqlite:////"):
        return url

    raw_path = url.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return url

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def _env_bool(name: str, default: bool = False) -> bool:
    """Читает логическое значение из переменной окружения."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_csv(name: str, default: list[str] | None = None) -> list[str]:
    """Читает список значений, разделённых запятыми."""
    raw = os.getenv(name)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def _looks_like_weak_secret(value: str) -> bool:
    """Отбрасывает известные заглушки и слишком короткие JWT-секреты."""
    normalized = value.strip().lower()
    known_placeholders = {
        "secret",
        "dev-secret-key",
        "change-me",
        "changeme",
        "jwt-secret",
        "your-secret-key",
        "please-change-me",
        "paste-random-secret-here",
    }
    return normalized in known_placeholders or len(value) < 32


class Config:
    """Единый объект настроек приложения.

    ``DEV_MODE`` управляет только разработческими послаблениями. Он не должен
    использоваться как замена настоящей авторизации в production.
    """

    def __init__(self) -> None:
        self.APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
        if self.APP_ENV not in {"development", "test", "production"}:
            raise RuntimeError(
                "APP_ENV must be one of: development, test, production"
            )

        self.DEV_MODE = _env_bool(
            "DEV_MODE",
            default=self.APP_ENV in {"development", "test"},
        )

        # Production и DEV_MODE=true — противоречащие друг другу настройки.
        if self.APP_ENV == "production" and self.DEV_MODE:
            raise RuntimeError("DEV_MODE must be false when APP_ENV=production")

        self.DATABASE_URL = _normalize_database_url(
            os.getenv(
                "DATABASE_URL",
                f"sqlite:///{(DATA_DIR / 'signage.db').as_posix()}",
            )
        )

        # Поддержка старого имени SECRET_KEY оставлена только для плавной миграции.
        raw_secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY")
        self.SECRET_KEY_IS_EPHEMERAL = False

        if raw_secret:
            self.SECRET_KEY = raw_secret
        elif self.DEV_MODE:
            # В dev можно не хранить секрет. Цена удобства: после перезапуска все
            # выданные ранее токены перестанут работать.
            self.SECRET_KEY = secrets.token_urlsafe(48)
            self.SECRET_KEY_IS_EPHEMERAL = True
        else:
            raise RuntimeError(
                "JWT_SECRET_KEY is required when DEV_MODE=false. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )

        if not self.DEV_MODE and _looks_like_weak_secret(self.SECRET_KEY):
            raise RuntimeError(
                "JWT_SECRET_KEY is weak or looks like a placeholder. "
                "Use a random value with at least 32 characters."
            )

        self.ALGORITHM = os.getenv("ALGORITHM", "HS256").strip().upper()
        if self.ALGORITHM not in {"HS256", "HS384", "HS512"}:
            raise RuntimeError("Only HS256, HS384 and HS512 are supported")

        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480")
        )
        if self.ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
            raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than zero")

        self.PASSWORD_MIN_LENGTH = int(
            os.getenv("PASSWORD_MIN_LENGTH", "8" if self.DEV_MODE else "12")
        )
        if self.PASSWORD_MIN_LENGTH < 8:
            raise RuntimeError("PASSWORD_MIN_LENGTH cannot be less than 8")
        self.PASSWORD_REQUIRE_MIXED = _env_bool("PASSWORD_REQUIRE_MIXED", True)

        # Dev-функции выключены по умолчанию даже в development. Их нужно
        # включить явно в .env.development.example.
        self.ENABLE_DEV_BOOTSTRAP = _env_bool("ENABLE_DEV_BOOTSTRAP", False)
        self.DEV_BOOTSTRAP_RESET_PASSWORDS = _env_bool(
            "DEV_BOOTSTRAP_RESET_PASSWORDS", False
        )
        self.ENABLE_PUBLIC_REGISTER_IN_DEV = _env_bool(
            "ENABLE_PUBLIC_REGISTER_IN_DEV", False
        )
        self.SHOW_DEV_LOGIN_HINTS = _env_bool("SHOW_DEV_LOGIN_HINTS", False)

        if not self.DEV_MODE and any(
            {
                self.ENABLE_DEV_BOOTSTRAP,
                self.DEV_BOOTSTRAP_RESET_PASSWORDS,
                self.ENABLE_PUBLIC_REGISTER_IN_DEV,
                self.SHOW_DEV_LOGIN_HINTS,
            }
        ):
            raise RuntimeError(
                "Development-only options cannot be enabled when DEV_MODE=false"
            )

        # Учётная запись для первого запуска пустой production-базы.
        self.INITIAL_ADMIN_USERNAME = os.getenv(
            "INITIAL_ADMIN_USERNAME", "admin"
        ).strip()
        self.INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD") or None
        self.INITIAL_ADMIN_EMAIL = os.getenv("INITIAL_ADMIN_EMAIL") or None
        self.INITIAL_ADMIN_FULL_NAME = os.getenv(
            "INITIAL_ADMIN_FULL_NAME", "Administrator"
        ).strip()

        # Удобные локальные учётные записи. Они используются только при
        # DEV_MODE=true + ENABLE_DEV_BOOTSTRAP=true.
        self.DEV_ADMIN_USERNAME = os.getenv("DEV_ADMIN_USERNAME", "admin").strip()
        self.DEV_ADMIN_PASSWORD = os.getenv("DEV_ADMIN_PASSWORD", "admin123")
        self.DEV_HR_USERNAME = os.getenv("DEV_HR_USERNAME", "hr").strip()
        self.DEV_HR_PASSWORD = os.getenv("DEV_HR_PASSWORD", "12345")

        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "8000"))

        # При размещении frontend и backend на одном origin CORS не нужен.
        self.CORS_ALLOWED_ORIGINS = _env_csv(
            "CORS_ALLOWED_ORIGINS",
            ["*"] if self.DEV_MODE else [],
        )
        if not self.DEV_MODE and "*" in self.CORS_ALLOWED_ORIGINS:
            raise RuntimeError("Wildcard CORS is forbidden when DEV_MODE=false")

        # Swagger удобен разработчику, но обычно не нужен на рабочем сервере.
        self.ENABLE_API_DOCS = _env_bool("ENABLE_API_DOCS", self.DEV_MODE)


config = Config()
