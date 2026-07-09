"""Add user profile and status fields.

Revision ID: 003_users_profile_fields
Revises: 002_contract_schema
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "003_users_profile_fields"
down_revision = "002_contract_schema"
branch_labels = None
depends_on = None

USERS_TABLE = "users"
EMAIL_INDEX = "ix_users_email_unique"


def _get_column_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(USERS_TABLE)}


def _get_index_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(USERS_TABLE)}


def upgrade() -> None:
    """Upgrade schema from 002_contract_schema to 003_users_profile_fields."""
    columns = _get_column_names()

    if "full_name" not in columns:
        op.add_column(
            USERS_TABLE,
            sa.Column("full_name", sa.String(length=100), nullable=True),
        )

    if "email" not in columns:
        op.add_column(
            USERS_TABLE,
            sa.Column("email", sa.String(length=100), nullable=True),
        )

    if "is_active" not in columns:
        op.add_column(
            USERS_TABLE,
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
    else:
        # На БД, пропатченной вручную до этой миграции, колонка может быть nullable
        # и без заполненных значений. Для ORM достаточно привести NULL к True.
        op.execute(sa.text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))

    if "updated_at" not in columns:
        op.add_column(
            USERS_TABLE,
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "last_login" not in columns:
        op.add_column(
            USERS_TABLE,
            sa.Column("last_login", sa.DateTime(), nullable=True),
        )

    # SQLite не умеет нормально добавлять UNIQUE constraint через ALTER TABLE,
    # поэтому используем уникальный индекс. Несколько NULL в SQLite допустимы.
    indexes = _get_index_names()
    if EMAIL_INDEX not in indexes:
        op.create_index(EMAIL_INDEX, USERS_TABLE, ["email"], unique=True)


def downgrade() -> None:
    """Downgrade schema back to 002_contract_schema."""
    indexes = _get_index_names()
    if EMAIL_INDEX in indexes:
        op.drop_index(EMAIL_INDEX, table_name=USERS_TABLE)

    columns = _get_column_names()
    columns_to_drop = [
        column
        for column in ("last_login", "updated_at", "is_active", "email", "full_name")
        if column in columns
    ]

    if not columns_to_drop:
        return

    # batch_alter_table нужен для SQLite: DROP COLUMN реализуется через
    # пересоздание таблицы, если обычный ALTER не поддерживается.
    with op.batch_alter_table(USERS_TABLE) as batch_op:
        for column in columns_to_drop:
            batch_op.drop_column(column)
