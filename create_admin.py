from backend.database import SessionLocal
from backend.models import User
from backend.auth import get_password_hash

USERNAME = "admin"
PASSWORD = "admin123"

db = SessionLocal()

try:
    user = db.query(User).filter(User.username == USERNAME).first()

    if user:
        user.password_hash = get_password_hash(PASSWORD)
        user.role = "admin"
        user.full_name = "Администратор"
        user.email = "admin@example.local"
        user.is_active = True
        print("Existing admin user updated")
    else:
        user = User(
            username=USERNAME,
            password_hash=get_password_hash(PASSWORD),
            role="admin",
            full_name="Администратор",
            email="admin@example.local",
            is_active=True,
        )
        db.add(user)
        print("Admin user created")

    db.commit()
    print(f"Login: {USERNAME}")
    print(f"Password: {PASSWORD}")

finally:
    db.close()
