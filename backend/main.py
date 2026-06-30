from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from backend.api import slides, active_slides, screens, auth_router
from backend.websocket_manager import router as websocket_router
from backend.database import engine, Base
from backend.config import BASE_DIR, config

FRONTEND_DIR = BASE_DIR / "frontend"

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Digital Signage API",
    description="System for managing digital signage displays",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(active_slides.router, prefix="/api", tags=["slides"])
app.include_router(slides.router, prefix="/api", tags=["slides"])
app.include_router(screens.router, prefix="/api", tags=["screens"])
app.include_router(auth_router.router, prefix="/api", tags=["auth"])
app.include_router(websocket_router, prefix="", tags=["websocket"])

@app.get("/api/generate-code")
def generate_code():
    from backend.database import SessionLocal
    from backend.models import Screen
    import random
    
    db = SessionLocal()
    try:
        existing_codes = [s[0] for s in db.query(Screen.code).all()]
        for _ in range(100):
            code = f"{random.randint(0, 999):03d}"
            if code not in existing_codes:
                return {"code": code}
        raise HTTPException(status_code=500, detail="No free codes available")
    finally:
        db.close()

@app.get("/main.html")
async def get_main():
    return FileResponse(FRONTEND_DIR / "main.html")

@app.get("/admin.html")
async def get_admin():
    return FileResponse(FRONTEND_DIR / "admin.html")

@app.get("/index.html")
async def get_index():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/")
def root():
    return {
        "message": "Digital Signage API v2.0",
        "docs": "/docs",
        "admin": "/admin.html",
        "display": "/index.html",
        "login": "/main.html"
    }

@app.on_event("startup")
async def startup_event():
    print(" Digital Signage API started")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=True)