
# backend/api/uploads.py
# Загрузка изображений из админки. Раздача файлов делается через app.mount("/uploads", StaticFiles(...)).

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from backend.auth import require_hr_or_admin
from backend.config import BASE_DIR
from backend.models import User


router = APIRouter(dependencies=[Depends(require_hr_or_admin)])

UPLOADS_DIR = BASE_DIR / "uploads"
ALLOWED_FOLDERS = {"slides", "backgrounds"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024


def _safe_extension(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image extension")
    return suffix


@router.post("/uploads/images")
async def upload_image(
    file: UploadFile = File(...),
    folder: str = Query("slides", pattern="^(slides|backgrounds)$"),
    current_user: User = Depends(require_hr_or_admin),
) -> dict[str, str | int | bool]:
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(status_code=400, detail="Invalid upload folder")

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    extension = _safe_extension(file.filename or "")
    target_dir = UPLOADS_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large")

    filename = f"{uuid4().hex}{extension}"
    target_path = target_dir / filename
    target_path.write_bytes(content)

    url = f"/uploads/{folder}/{filename}"
    return {
        "ok": True,
        "url": url,
        "filename": filename,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(content),
    }
