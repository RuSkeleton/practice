
"""Bring database schema to the screen-client/server contract.

Revision ID: 002_contract_schema
Revises: 001_initial_tables
Create Date: 2026-07-07
"""

from __future__ import annotations

import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "002_contract_schema"
down_revision = "001_initial_tables"
branch_labels = None
depends_on = None

SCHEDULE_VERSION_KEY = "schedule_version"


def _safe_json_loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return default if value is None else value


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _old_type_to_kind(old_type: str | None) -> str:
    mapping = {
        "text": "announcement",
        "announcement": "announcement",
        "image": "image",
        "greeting": "greeting",
        "birthday": "greeting",
        "metric": "metric",
    }
    return mapping.get((old_type or "").lower(), "announcement")


def _priority_to_frequency_mode(priority: Any) -> int:
    try:
        value = int(priority or 0)
    except (TypeError, ValueError):
        value = 0

    if value <= 0:
        return 1
    if value == 1:
        return 2
    return 3


def _make_background(kind: str) -> dict[str, str]:
    gradient_by_kind = {
        "announcement": "announcement",
        "image": "image",
        "greeting": "greeting",
        "metric": "metric",
    }
    return {
        "type": "gradient",
        "value": gradient_by_kind.get(kind, "announcement"),
    }


def _make_text_element(
    element_id: str,
    role: str,
    value: str,
    x: int,
    y: int,
    width: int,
    height: int,
    font_size: int,
    *,
    font_weight: int | None = None,
    align: str | None = None,
    z_index: int = 2,
) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "fontSize": font_size,
        "color": "#ffffff",
        "zIndex": z_index,
    }
    if font_weight is not None:
        layout["fontWeight"] = font_weight
    if align is not None:
        layout["align"] = align

    return {
        "id": element_id,
        "type": "text",
        "role": role,
        "value": value or "",
        "layout": layout,
    }


def _make_elements(
    *,
    kind: str,
    title: str | None,
    content: str | None,
    extra_data: dict[str, Any],
) -> list[dict[str, Any]]:
    safe_title = title or "Без названия"
    safe_content = content or ""

    if kind == "image":
        elements = [
            _make_text_element(
                "title",
                "title",
                safe_title,
                160,
                80,
                1600,
                100,
                58,
                font_weight=800,
                align="center",
            )
        ]
        if safe_content:
            elements.append(
                {
                    "id": "main_image",
                    "type": "image",
                    "role": "main_image",
                    "src": safe_content,
                    "alt": safe_title,
                    "layout": {
                        "x": 420,
                        "y": 220,
                        "width": 1080,
                        "height": 640,
                        "objectFit": "contain",
                        "zIndex": 2,
                    },
                }
            )
        return elements

    if kind == "greeting":
        person_name = str(extra_data.get("name") or safe_title)
        reason = str(extra_data.get("reason") or safe_title)
        return [
            _make_text_element(
                "title",
                "title",
                reason,
                160,
                120,
                1600,
                120,
                68,
                font_weight=800,
                align="center",
            ),
            _make_text_element(
                "name",
                "person_name",
                person_name,
                220,
                330,
                1480,
                120,
                56,
                font_weight=700,
                align="center",
            ),
            _make_text_element(
                "body",
                "body",
                safe_content,
                260,
                520,
                1400,
                220,
                40,
                align="center",
            ),
        ]

    if kind == "metric":
        return [
            _make_text_element(
                "title",
                "title",
                safe_title,
                160,
                120,
                1600,
                120,
                64,
                font_weight=800,
                align="center",
            ),
            _make_text_element(
                "value",
                "metric_value",
                safe_content,
                260,
                350,
                1400,
                220,
                96,
                font_weight=800,
                align="center",
            ),
        ]

    return [
        _make_text_element(
            "title",
            "title",
            safe_title,
            160,
            120,
            1600,
            120,
            64,
            font_weight=800,
            align="center",
        ),
        _make_text_element(
            "body",
            "body",
            safe_content,
            220,
            320,
            1480,
            420,
            42,
            align="center",
        ),
    ]


def _create_contract_slides_table(table_name: str = "slides") -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("template_key", sa.String(length=100), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False, server_default="announcement"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_date", sa.DateTime(), nullable=False),
        sa.Column("end_date", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("duration_slots", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("frequency_mode", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("hard_interval", sa.Integer(), nullable=True),
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("alarm_type", sa.String(length=50), nullable=True),
        sa.Column("background", sa.JSON(), nullable=False),
        sa.Column("elements", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "duration_slots >= 1 AND duration_slots <= 4",
            name="ck_slides_duration_slots_range",
        ),
        sa.CheckConstraint(
            "frequency_mode >= 1 AND frequency_mode <= 4",
            name="ck_slides_frequency_mode_range",
        ),
        sa.CheckConstraint(
            "(frequency_mode != 4 AND hard_interval IS NULL) OR "
            "(frequency_mode = 4 AND hard_interval > 1)",
            name="ck_slides_hard_interval_consistency",
        ),
    )
    op.create_index(
        "ix_slides_active_period",
        table_name,
        ["is_active", "start_date", "end_date"],
        unique=False,
    )
    op.create_index(
        "ix_slides_hard_interval",
        table_name,
        ["frequency_mode", "hard_interval"],
        unique=False,
    )
    op.create_index(
        "ix_slides_emergency",
        table_name,
        ["is_emergency", "alarm_type"],
        unique=False,
    )


def _create_schedule_windows_table() -> None:
    op.create_table(
        "schedule_windows",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("slot_duration", sa.Integer(), nullable=False, server_default="15"),
        sa.Column(
            "window_size_seconds",
            sa.Integer(),
            nullable=False,
            server_default="3600",
        ),
        sa.Column("queue", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "window_end > window_start",
            name="ck_schedule_windows_valid_period",
        ),
        sa.CheckConstraint(
            "slot_duration > 0",
            name="ck_schedule_windows_slot_duration_positive",
        ),
        sa.CheckConstraint(
            "window_size_seconds > 0",
            name="ck_schedule_windows_window_size_positive",
        ),
    )
    op.create_index("ix_schedule_windows_id", "schedule_windows", ["id"], unique=False)
    op.create_index(
        "ix_schedule_windows_window_start",
        "schedule_windows",
        ["window_start"],
        unique=False,
    )
    op.create_index(
        "ix_schedule_windows_window_end",
        "schedule_windows",
        ["window_end"],
        unique=False,
    )


def _create_system_settings_table() -> None:
    op.create_table(
        "system_settings",
        sa.Column("setting_key", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("int_value", sa.Integer(), nullable=True),
        sa.Column("str_value", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "slides" in table_names:
        old_columns = {column["name"] for column in inspector.get_columns("slides")}
        if {"type", "title", "content"}.issubset(old_columns):
            rows = [dict(row._mapping) for row in bind.execute(sa.text("SELECT * FROM slides"))]

            _create_contract_slides_table("slides_new")

            insert_sql = sa.text(
                """
                INSERT INTO slides_new (
                    id,
                    name,
                    template_key,
                    kind,
                    revision,
                    start_date,
                    end_date,
                    is_active,
                    duration_slots,
                    frequency_mode,
                    hard_interval,
                    is_emergency,
                    alarm_type,
                    background,
                    elements,
                    created_by,
                    updated_by,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :name,
                    :template_key,
                    :kind,
                    :revision,
                    :start_date,
                    :end_date,
                    :is_active,
                    :duration_slots,
                    :frequency_mode,
                    :hard_interval,
                    :is_emergency,
                    :alarm_type,
                    :background,
                    :elements,
                    :created_by,
                    :updated_by,
                    :created_at,
                    :updated_at
                )
                """
            )

            for row in rows:
                old_type = row.get("type")
                kind = _old_type_to_kind(old_type)
                title = row.get("title")
                content = row.get("content")
                extra_data = _safe_json_loads(row.get("extra_data"), {})
                if not isinstance(extra_data, dict):
                    extra_data = {}

                bind.execute(
                    insert_sql,
                    {
                        "id": row["id"],
                        "name": title or f"Слайд {row['id']}",
                        "template_key": old_type,
                        "kind": kind,
                        "revision": 1,
                        "start_date": row["start_date"],
                        "end_date": row["end_date"],
                        "is_active": bool(row.get("is_active", True)),
                        "duration_slots": 1,
                        "frequency_mode": _priority_to_frequency_mode(row.get("priority")),
                        "hard_interval": None,
                        "is_emergency": False,
                        "alarm_type": None,
                        "background": _json_dump(_make_background(kind)),
                        "elements": _json_dump(
                            _make_elements(
                                kind=kind,
                                title=title,
                                content=content,
                                extra_data=extra_data,
                            )
                        ),
                        "created_by": None,
                        "updated_by": None,
                        "created_at": row.get("created_at"),
                        "updated_at": row.get("updated_at"),
                    },
                )

            op.drop_table("slides")
            op.rename_table("slides_new", "slides")
        else:
            # Таблица уже похожа на контрактную: не трогаем данные, но недостающие
            # таблицы ниже всё равно будут созданы.
            pass
    else:
        _create_contract_slides_table("slides")

    table_names = set(sa.inspect(bind).get_table_names())

    if "schedule_windows" not in table_names:
        _create_schedule_windows_table()

    if "system_settings" not in table_names:
        _create_system_settings_table()

    bind.execute(
        sa.text(
            """
            INSERT INTO system_settings (setting_key, int_value, str_value, updated_at)
            VALUES (:key, 0, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(setting_key) DO NOTHING
            """
        ),
        {"key": SCHEDULE_VERSION_KEY},
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "system_settings" in table_names:
        op.drop_table("system_settings")

    if "schedule_windows" in table_names:
        op.drop_index("ix_schedule_windows_window_end", table_name="schedule_windows")
        op.drop_index("ix_schedule_windows_window_start", table_name="schedule_windows")
        op.drop_index("ix_schedule_windows_id", table_name="schedule_windows")
        op.drop_table("schedule_windows")

    if "slides" in table_names:
        columns = {column["name"] for column in inspector.get_columns("slides")}
        if {"name", "kind", "background", "elements"}.issubset(columns):
            rows = [dict(row._mapping) for row in bind.execute(sa.text("SELECT * FROM slides"))]

            op.create_table(
                "slides_old",
                sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
                sa.Column("type", sa.String(length=50), nullable=False),
                sa.Column("title", sa.String(length=200), nullable=True),
                sa.Column("content", sa.Text(), nullable=True),
                sa.Column("extra_data", sa.JSON(), nullable=True),
                sa.Column("start_date", sa.DateTime(), nullable=False),
                sa.Column("end_date", sa.DateTime(), nullable=False),
                sa.Column("priority", sa.Integer(), server_default="0", nullable=True),
                sa.Column("views", sa.Integer(), server_default="0", nullable=True),
                sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=True),
                sa.Column("is_auto_generated", sa.Boolean(), server_default=sa.text("0"), nullable=True),
                sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
                sa.Column("updated_at", sa.DateTime(), nullable=True),
            )
            op.create_index("ix_slides_id", "slides_old", ["id"], unique=False)

            insert_sql = sa.text(
                """
                INSERT INTO slides_old (
                    id,
                    type,
                    title,
                    content,
                    extra_data,
                    start_date,
                    end_date,
                    priority,
                    views,
                    is_active,
                    is_auto_generated,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :type,
                    :title,
                    :content,
                    :extra_data,
                    :start_date,
                    :end_date,
                    :priority,
                    :views,
                    :is_active,
                    :is_auto_generated,
                    :created_at,
                    :updated_at
                )
                """
            )

            for row in rows:
                elements = _safe_json_loads(row.get("elements"), [])
                content = ""
                if isinstance(elements, list):
                    body = next(
                        (
                            element
                            for element in elements
                            if isinstance(element, dict)
                            and element.get("type") == "text"
                            and element.get("role") in {"body", "metric_value"}
                        ),
                        None,
                    )
                    if body is not None:
                        content = str(body.get("value") or "")

                    image = next(
                        (
                            element
                            for element in elements
                            if isinstance(element, dict)
                            and element.get("type") == "image"
                            and element.get("src")
                        ),
                        None,
                    )
                    if image is not None:
                        content = str(image.get("src") or content)

                frequency_mode = int(row.get("frequency_mode") or 1)
                priority = 0 if frequency_mode <= 1 else 1 if frequency_mode == 2 else 2

                bind.execute(
                    insert_sql,
                    {
                        "id": row["id"],
                        "type": row.get("template_key") or row.get("kind") or "text",
                        "title": row.get("name"),
                        "content": content,
                        "extra_data": _json_dump({}),
                        "start_date": row.get("start_date"),
                        "end_date": row.get("end_date"),
                        "priority": priority,
                        "views": 0,
                        "is_active": bool(row.get("is_active", True)),
                        "is_auto_generated": False,
                        "created_at": row.get("created_at"),
                        "updated_at": row.get("updated_at"),
                    },
                )

            op.drop_table("slides")
            op.rename_table("slides_old", "slides")
