
"""Безопасная смена пароля пользователя напрямую через SQLite/SQLAlchemy.

Полезно при переходе со старой базы, когда production-start блокируется из-за
admin/admin123, а войти в интерфейс уже невозможно.

Запуск из корня проекта:
    python scripts/change_user_password.py admin
"""

from __future__ import annotations

import argparse
from getpass import getpass

from backend import auth, crud
from backend.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Change a Digital Signage password")
    parser.add_argument("username", help="Existing username")
    args = parser.parse_args()

    new_password = getpass("Новый пароль: ")
    confirmation = getpass("Повторите новый пароль: ")
    if new_password != confirmation:
        raise SystemExit("Пароли не совпадают")

    db = SessionLocal()
    try:
        user = crud.get_user_by_username(db, args.username)
        if user is None:
            raise SystemExit("Пользователь не найден")

        auth.validate_password_strength(new_password, username=user.username)
        user.password_hash = auth.get_password_hash(new_password)
        user.auth_version = int(user.auth_version or 1) + 1
        db.commit()
        print(f"Пароль пользователя '{user.username}' изменён")
    finally:
        db.close()


if __name__ == "__main__":
    main()
