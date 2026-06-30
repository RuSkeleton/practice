import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")


def _normalize_database_url(url: str) -> str:
    """
    Делает относительные sqlite-пути независимыми от рабочей папки запуска.
    Например sqlite:///./data/signage.db всегда будет вести в <корень проекта>/data/signage.db.
    """
    if not url.startswith("sqlite:///") or url.startswith("sqlite:////"):
        return url

    raw_path = url.replace("sqlite:///", "", 1)

    if raw_path == ":memory:":
        return url

    db_path = Path(raw_path)

    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)

    return f"sqlite:///{db_path.as_posix()}"


class Config:
    DATABASE_URL = _normalize_database_url(
        os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'signage.db').as_posix()}")
    )
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    ALGORITHM = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 480))
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8000))


config = Config()