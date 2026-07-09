from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.api import auth_router
from backend.api.slides import router as slides_router
from backend.api.screens import router as screens_admin_router
from backend.config import BASE_DIR, config
from backend.database import Base, engine
from backend.models import Screen
from backend.routers import screens as screen_client_router
from backend.routers import uploads as uploads_router
from backend.routers import websocket as screens_websocket_router

# Нужно временно для удобного доступа к макету editor.html
from fastapi.staticfiles import StaticFiles


FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Digital Signage API",
    description="System for managing digital signage displays",
    version="2.0.0",
)

app.mount(
    "/static",
    StaticFiles(directory="frontend/static"),
    name="static"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api", tags=["auth"])
app.include_router(screen_client_router.router, prefix="/api", tags=["screen-client"])
app.include_router(uploads_router.router, prefix="/api", tags=["uploads"])
app.include_router(screens_websocket_router.router, tags=["screen-websocket"])
app.include_router(slides_router, prefix="/api", tags=["slides"])
app.include_router(screens_admin_router, prefix="/api", tags=["screens"])

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
async def go_editor():
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
    from backend.database import SessionLocal
    from backend import models, auth

    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            admin = models.User(
                username="admin",
                password_hash=auth.get_password_hash("admin123"),
                role="admin",
                full_name="Administrator",
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("Создан администратор по умолчанию: admin / admin123")
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=True)