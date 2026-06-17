"""Валидация JWT access_token, выпущенного Keycloak.

reports-api — resource server (bearer-only). Токен приходит в заголовке
Authorization: Bearer <jwt> (его подставляет bionicpro-auth). Здесь мы:
  1. достаём kid из заголовка и берём соответствующий публичный ключ из JWKS;
  2. проверяем RS256-подпись, срок действия (exp) и issuer;
  3. возвращаем личность пользователя из claim'ов.

Ключевой момент безопасности: username берётся ИСКЛЮЧИТЕЛЬНО из проверенного
токена — клиент не может подменить, под кого запрашивается отчёт.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings

settings = get_settings()
_bearer = HTTPBearer(auto_error=False)

# PyJWKClient кеширует ключи и сам ходит за обновлением при ротации.
_jwk_client = PyJWKClient(settings.jwks_url)


@dataclass
class CurrentUser:
    username: str
    sub: str
    roles: list


def _decode(token: str) -> dict:
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(token).key
    except Exception:  # сеть/неизвестный kid
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="cannot resolve signing key",
        )

    options = {"verify_aud": bool(settings.expected_audience)}
    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=settings.issuer,
            audience=settings.expected_audience or None,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
        )


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    """FastAPI-зависимость: возвращает проверенного пользователя или 401."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    claims = _decode(creds.credentials)
    username = claims.get("preferred_username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token has no preferred_username",
        )
    return CurrentUser(
        username=username,
        sub=claims.get("sub", ""),
        roles=claims.get("realm_access", {}).get("roles", []),
    )
