"""Точка входа FastAPI-приложения."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import auth_router
from backend.api.screens import router as screens_admin_router
from backend.api.slides import router as slides_router
from backend.config import BASE_DIR, config
from backend.database import SessionLocal
from backend.routers import screens as screen_client_router
from backend.routers import uploads as uploads_router
from backend.routers import websocket as screens_websocket_router
from backend.security_bootstrap import bootstrap_auth


FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Инициализация приложения без скрытого изменения схемы БД.

    ``Base.metadata.create_all`` намеренно удалён. Структурой базы управляет
    только Alembic, поэтому до запуска сервера выполняется:

        python -m alembic upgrade head

    Здесь остаётся только безопасный bootstrap пользователей.
    """
    print("Digital Signage API started")
    print(f"APP_ENV={config.APP_ENV}; DEV_MODE={config.DEV_MODE}")

    db = SessionLocal()
    try:
        bootstrap_auth(db)
    finally:
        db.close()

    yield


app = FastAPI(
    title="Digital Signage API",
    description="System for managing digital signage displays",
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs" if config.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if config.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if config.ENABLE_API_DOCS else None,
)

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR / "static"),
    name="static",
)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# При одном origin CORS не нужен. В dev разрешён wildcard, но browser credentials
# отключены: приложение использует заголовок Bearer, а не cookie-сессию.
if config.CORS_ALLOWED_ORIGINS:
    wildcard = "*" in config.CORS_ALLOWED_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ALLOWED_ORIGINS,
        allow_credentials=not wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Сначала подключается протокол экранного клиента, затем административные API.
app.include_router(auth_router.router, prefix="/api", tags=["auth"])
app.include_router(screen_client_router.router, prefix="/api", tags=["screen-client"])
app.include_router(uploads_router.router, prefix="/api", tags=["uploads"])
app.include_router(screens_websocket_router.router, tags=["screen-websocket"])
app.include_router(slides_router, prefix="/api", tags=["slides"])
app.include_router(screens_admin_router, prefix="/api", tags=["screens-admin"])


@app.get("/main.html")
async def get_main():
    return FileResponse(FRONTEND_DIR / "main.html")


@app.get("/admin.html")
async def get_admin():
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/index.html")
async def get_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/editor.html")
async def get_editor():
    return FileResponse(FRONTEND_DIR / "editor.html")


@app.get("/utils.js")
async def get_utils_js():
    return FileResponse(FRONTEND_DIR / "utils.js")


@app.get("/image_cache.js")
async def get_image_cache_js():
    return FileResponse(FRONTEND_DIR / "image_cache.js")


@app.get("/slide_rendering.js")
async def get_slide_rendering_js():
    return FileResponse(FRONTEND_DIR / "slide_rendering.js")


@app.get("/")
def root():
    response = {
        "message": "Digital Signage API v2.1",
        "admin": "/admin.html",
        "display": "/index.html",
        "login": "/main.html",
        "screen_ws": "/ws/screens",
    }
    if config.ENABLE_API_DOCS:
        response["docs"] = "/docs"
    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEV_MODE,
    )
