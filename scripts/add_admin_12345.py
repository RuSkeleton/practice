from __future__ import annotations

from sqlalchemy import func

from backend import auth, models
from backend.database import SessionLocal


USERNAME = "admin"
PASSWORD = "12345"


def main() -> None:
    db = SessionLocal()

    try:
        user = (
            db.query(models.User)
            .filter(func.lower(models.User.username) == USERNAME.lower())
            .first()
        )

        if user is None:
            user = models.User(
                username=USERNAME,
                password_hash=auth.get_password_hash(PASSWORD),
                role="admin",
                full_name="Administrator",
                is_active=True,
            )

            if hasattr(user, "auth_version"):
                user.auth_version = 1

            db.add(user)
            action = "создан"
        else:
            user.password_hash = auth.get_password_hash(PASSWORD)
            user.role = "admin"
            user.is_active = True

            if not user.full_name:
                user.full_name = "Administrator"

            if hasattr(user, "auth_version"):
                user.auth_version = int(user.auth_version or 1) + 1

            action = "восстановлен и обновлён"

        db.commit()
        db.refresh(user)

        print(f"Пользователь '{USERNAME}' {action}.")
        print(f"Роль: {user.role}")
        print(f"Активен: {user.is_active}")
        print(f"Логин: {USERNAME}")
        print(f"Пароль: {PASSWORD}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
