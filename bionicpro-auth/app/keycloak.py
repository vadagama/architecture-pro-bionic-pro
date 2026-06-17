"""Интеграция с Keycloak: построение authorize-URL, обмен кода на токены,
обновление по refresh_token, logout. Все server-to-server вызовы — через httpx.
"""
import base64
import json
import time
from urllib.parse import urlencode

import httpx

from .config import Settings


class KeycloakError(Exception):
    pass


def build_authorize_url(settings: Settings, state: str, code_challenge: str) -> str:
    """URL формы логина Keycloak для Authorization Code Flow + PKCE (S256)."""
    params = {
        "client_id": settings.client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": settings.redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.authorization_endpoint}?{urlencode(params)}"


async def exchange_code(settings: Settings, code: str, code_verifier: str) -> dict:
    """Меняет authorization code + PKCE verifier на набор токенов."""
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "code_verifier": code_verifier,
    }
    return await _post_token(settings, data)


async def refresh_tokens(settings: Settings, refresh_token: str) -> dict:
    """Обновляет access_token (и обычно refresh_token) по refresh_token."""
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "refresh_token": refresh_token,
    }
    return await _post_token(settings, data)


async def logout(settings: Settings, refresh_token: str) -> None:
    """Гасит сессию в Keycloak (отзыв refresh_token)."""
    data = {
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            settings.logout_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )


async def _post_token(settings: Settings, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            settings.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        raise KeycloakError(f"token endpoint {resp.status_code}: {resp.text}")
    return resp.json()


def decode_token_claims(access_token: str) -> dict:
    """Извлекает payload JWT без проверки подписи (для имени/ролей в UI).

    Проверка подписи на стороне ресурса (reports-api) — отдельная задача;
    здесь нужны только claims для отображения и привязки сессии.
    """
    try:
        payload_b64 = access_token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded)
    except (IndexError, ValueError):
        return {}


def access_expiry(token_response: dict) -> float:
    """Абсолютное время истечения access_token из expires_in."""
    expires_in = int(token_response.get("expires_in", 0))
    return time.time() + expires_in
