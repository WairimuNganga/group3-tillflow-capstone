from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.requests import Request
from starlette.responses import Response

from web.config import settings


def cookie_path() -> str:
    """Scope browser state to the public app prefix, or root when local."""
    return settings.base_path.rstrip("/") or "/"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.session_secret, salt="tillflow-web-session")


def load_session(request: Request) -> dict[str, Any]:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return {}
    try:
        data = _serializer().loads(raw)
        return data if isinstance(data, dict) else {}
    except BadSignature:
        return {}


def save_session(response: Response, data: dict[str, Any]) -> None:
    token = _serializer().dumps(data)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 12,
        path=cookie_path(),
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path=cookie_path())


def ensure_csrf(request: Request, response: Response) -> str:
    token = request.cookies.get(settings.csrf_cookie_name)
    if not token:
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            settings.csrf_cookie_name,
            token,
            httponly=False,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=60 * 60 * 12,
            path=cookie_path(),
        )
    return token


def verify_csrf(request: Request, submitted: str | None) -> bool:
    expected = request.cookies.get(settings.csrf_cookie_name)
    if not expected or not submitted:
        return False
    return secrets.compare_digest(expected, submitted)
