from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import auth_router
from backend.config import BASE_DIR, config
from backend.database import Base, engine
from backend.models import Screen
from backend.routers import screens as screen_client_router
from backend.routers import uploads as uploads_router
from backend.routers import websocket as screens_websocket_router

FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Для учебного проекта оставляем автосоздание таблиц на случай свежей пустой БД.
# Основной способ изменения схемы — Alembic-миграции.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Digital Signage API",
    description="System for managing digital signage displays",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Старые роуты /api/slides/active, /api/screens/heartbeat и /ws/slides больше
# не подключаются: экранный клиент теперь работает по контракту full/patch schedule.
app.include_router(auth_router.router, prefix="/api", tags=["auth"])
app.include_router(screen_client_router.router, prefix="/api", tags=["screen-client"])
app.include_router(uploads_router.router, prefix="/api", tags=["uploads"])
app.include_router(screens_websocket_router.router, tags=["screen-websocket"])

app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


def _generate_free_screen_code() -> str:
    from backend.database import SessionLocal
    import random

    db = SessionLocal()
    try:
        existing_codes = {row[0] for row in db.query(Screen.code).all()}
        for _ in range(100):
            code = f"{random.randint(0, 999):03d}"
            if code not in existing_codes:
                return code
        raise HTTPException(status_code=500, detail="No free codes available")
    finally:
        db.close()


@app.get("/api/generate-code")
def generate_code():
    return {"code": _generate_free_screen_code()}


@app.get("/api/screens/generate-code")
def generate_screen_code():
    # Алиас под старую админку/прототип. Логику управления экранами команда
    # сможет потом перенести в отдельный актуальный admin-router.
    return {"code": _generate_free_screen_code()}


@app.get("/main.html")
async def get_main():
    return FileResponse(FRONTEND_DIR / "main.html")


@app.get("/admin.html")
async def get_admin():
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/index.html")
async def get_index():
    # Активный экранный клиент — новый full/patch/cache player.
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/")
def root():
    return {
        "message": "Digital Signage API v2.0",
        "docs": "/docs",
        "admin": "/admin.html",
        "display": "/index.html",
        "login": "/main.html",
        "screen_ws": "/ws/screens",
    }


@app.on_event("startup")
async def startup_event():
    print("Digital Signage API started")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=True)
