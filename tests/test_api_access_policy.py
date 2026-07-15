"""Регрессионная проверка: новый API нельзя случайно оставить публичным."""

from backend.main import app


PUBLIC_OPERATIONS = {
    ("get", "/api/public-config"),
    ("post", "/api/login"),
    ("post", "/api/screens/activate"),
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def test_only_allowlisted_api_operations_are_public() -> None:
    schema = app.openapi()
    unexpectedly_public: list[str] = []

    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/api/"):
            continue

        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            key = (method.lower(), path)
            if key in PUBLIC_OPERATIONS:
                continue
            if not operation.get("security"):
                unexpectedly_public.append(f"{method.upper()} {path}")

    assert unexpectedly_public == [], (
        "Найдены API-маршруты без JWT или screen token: "
        + ", ".join(unexpectedly_public)
    )


def test_public_registration_is_removed() -> None:
    assert "/api/register" not in app.openapi().get("paths", {})
