"""Alembic environment.

Ключевое изменение: Alembic и FastAPI читают один DATABASE_URL из
``backend.config``. Раньше приложение могло работать с одной SQLite-базой,
а миграции — незаметно применяться к другой из alembic.ini.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.config import config as app_config
from backend.database import Base

# Импорт регистрирует все таблицы в Base.metadata, что необходимо для
# ``alembic revision --autogenerate``.
from backend import models  # noqa: F401,E402


alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# ConfigParser использует % для интерполяции, поэтому экранируем его в URL.
alembic_config.set_main_option(
    "sqlalchemy.url",
    app_config.DATABASE_URL.replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Формирует SQL без реального подключения к базе."""
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Применяет миграции к базе из DATABASE_URL."""
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Для SQLite операции ALTER часто реализуются пересозданием таблицы.
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
