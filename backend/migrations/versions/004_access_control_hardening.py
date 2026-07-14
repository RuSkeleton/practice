"""Add revocable user sessions and screen device credentials.

Revision ID: 004_access_control_hardening
Revises: 003_users_profile_fields
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "004_access_control_hardening"
down_revision = "003_users_profile_fields"
branch_labels = None
depends_on = None

USERS_TABLE = "users"
SCREENS_TABLE = "screens"
SCREEN_TOKEN_INDEX = "ix_screens_device_token_hash_unique"


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    user_columns = _columns(USERS_TABLE)
    if "auth_version" not in user_columns:
        op.add_column(
            USERS_TABLE,
            sa.Column(
                "auth_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    screen_columns = _columns(SCREENS_TABLE)
    columns_to_add = {
        "pairing_expires_at": sa.Column(
            "pairing_expires_at", sa.DateTime(), nullable=True
        ),
        "device_token_hash": sa.Column(
            "device_token_hash", sa.String(length=64), nullable=True
        ),
        "token_created_at": sa.Column(
            "token_created_at", sa.DateTime(), nullable=True
        ),
        "activated_at": sa.Column(
            "activated_at", sa.DateTime(), nullable=True
        ),
    }

    for name, column in columns_to_add.items():
        if name not in screen_columns:
            op.add_column(SCREENS_TABLE, column)

    # Старые 3-значные коды становятся 6-значными, но специально не получают
    # срок действия. После миграции администратор должен перевыпустить pairing
    # code, поэтому прежний постоянный код не остаётся рабочим секретом.
    op.execute(
        sa.text(
            "UPDATE screens "
            "SET code = substr('000000' || code, -6, 6) "
            "WHERE length(code) < 6"
        )
    )

    indexes = _indexes(SCREENS_TABLE)
    if SCREEN_TOKEN_INDEX not in indexes:
        op.create_index(
            SCREEN_TOKEN_INDEX,
            SCREENS_TABLE,
            ["device_token_hash"],
            unique=True,
        )


def downgrade() -> None:
    indexes = _indexes(SCREENS_TABLE)
    if SCREEN_TOKEN_INDEX in indexes:
        op.drop_index(SCREEN_TOKEN_INDEX, table_name=SCREENS_TABLE)

    screen_columns = _columns(SCREENS_TABLE)
    columns_to_drop = [
        name
        for name in (
            "activated_at",
            "token_created_at",
            "device_token_hash",
            "pairing_expires_at",
        )
        if name in screen_columns
    ]
    if columns_to_drop:
        with op.batch_alter_table(SCREENS_TABLE) as batch_op:
            for name in columns_to_drop:
                batch_op.drop_column(name)

    user_columns = _columns(USERS_TABLE)
    if "auth_version" in user_columns:
        with op.batch_alter_table(USERS_TABLE) as batch_op:
            batch_op.drop_column("auth_version")
