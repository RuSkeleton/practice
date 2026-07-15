
"""Печатает случайный JWT-секрет, пригодный для production .env."""

import secrets


if __name__ == "__main__":
    print(secrets.token_urlsafe(48))
