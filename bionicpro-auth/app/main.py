"""bionicpro-auth — Backend-for-Frontend (Token Handler).

Реализует безопасную схему работы с токенами:
- Authorization Code Flow + PKCE (S256) инициируется на бэкенде;
- access/refresh токены, полученные от Keycloak, НЕ передаются фронтенду —
  они хранятся в памяти сервиса в зашифрованном виде и привязаны к сессии;
- фронт получает только сессионную cookie (HTTP-only, Secure);
- при истёкшем access_token сервис сам обновляет его по refresh_token;
- при каждом обращении к защищённому ресурсу выполняется ротация session id
  (защита от session fixation).
"""
import secrets
import time

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .config import get_settings
from . import keycloak
from .security import generate_pkce, new_state
from .sessions import SessionData, SessionStore, TransientStore

settings = get_settings()
app = FastAPI(title="bionicpro-auth", version="1.0.0")

# Фронт (SPA) ходит на BFF cross-origin с credentials: 'include'.
# Для отправки/приёма сессионной cookie нужен конкретный origin и
# allow_credentials=True (wildcard '*' с credentials не допускается).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = SessionStore(settings.fernet_key, settings.session_ttl_seconds)
transient = TransientStore(ttl_seconds=300)


# --- вспомогательное ------------------------------------------------------
def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")


async def _ensure_fresh_access(session_id: str, data: SessionData) -> SessionData:
    """Если access_token истёк — обновляет его по refresh_token и сохраняет."""
    if data.access_expires_at - 5 > time.time():
        return data
    token_response = await keycloak.refresh_tokens(settings, data.refresh_token)
    data.access_token = token_response["access_token"]
    data.refresh_token = token_response.get("refresh_token", data.refresh_token)
    data.access_expires_at = keycloak.access_expiry(token_response)
    sessions.update(session_id, data)
    return data


# --- роуты ----------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/auth/login")
async def login() -> RedirectResponse:
    """Старт авторизации: генерируем PKCE + state, редиректим на Keycloak.

    state привязывается к инициировавшему браузеру через короткоживущую
    HttpOnly-cookie `oauth_state`. В /auth/callback проверяем совпадение
    state из query-параметра и из cookie — это гарантирует, что callback
    обрабатывает тот же браузер, который запустил flow (защита от CSRF).
    """
    code_verifier, code_challenge = generate_pkce()
    state = new_state()
    transient.put(state, {"code_verifier": code_verifier})
    url = keycloak.build_authorize_url(settings, state, code_challenge)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=300,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/auth/callback",
    )
    return response


@app.get("/auth/callback")
async def callback(request: Request) -> Response:
    """Возврат от Keycloak: меняем code на токены, создаём сессию, ставим cookie."""
    error = request.query_params.get("error")
    if error:
        return RedirectResponse(f"{settings.frontend_url}/?error={error}", status_code=302)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return JSONResponse({"error": "missing code or state"}, status_code=400)

    # Проверяем, что state совпадает со значением в cookie браузера —
    # только тот браузер, который инициировал /auth/login, может завершить flow.
    cookie_state = request.cookies.get("oauth_state")
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        return JSONResponse({"error": "state mismatch"}, status_code=400)

    stashed = transient.pop(state)
    if stashed is None:
        return JSONResponse({"error": "invalid or expired state"}, status_code=400)

    try:
        token_response = await keycloak.exchange_code(settings, code, stashed["code_verifier"])
    except keycloak.KeycloakError:
        return JSONResponse({"error": "token exchange failed"}, status_code=502)

    claims = keycloak.decode_token_claims(token_response["access_token"])
    data = SessionData(
        access_token=token_response["access_token"],
        refresh_token=token_response.get("refresh_token", ""),
        access_expires_at=keycloak.access_expiry(token_response),
        sub=claims.get("sub", ""),
        username=claims.get("preferred_username", ""),
        roles=claims.get("realm_access", {}).get("roles", []),
    )
    session_id = sessions.create(data)

    response = RedirectResponse(settings.frontend_url, status_code=302)
    _set_session_cookie(response, session_id)
    # Удаляем одноразовую oauth_state cookie — она больше не нужна.
    response.delete_cookie(key="oauth_state", path="/auth/callback")
    return response


@app.get("/auth/me")
async def me(request: Request) -> Response:
    """Статус авторизации для фронта. Токены не возвращаются — только профиль."""
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        return JSONResponse({"authenticated": False}, status_code=401)
    data = sessions.get(session_id)
    if data is None:
        return JSONResponse({"authenticated": False}, status_code=401)
    return JSONResponse(
        {"authenticated": True, "username": data.username, "roles": data.roles}
    )


@app.post("/auth/logout")
async def logout_route(request: Request) -> Response:
    """Завершение сессии: отзыв в Keycloak + удаление локальной сессии и cookie."""
    session_id = request.cookies.get(settings.session_cookie_name)
    response = JSONResponse({"status": "logged_out"})
    if session_id:
        data = sessions.get(session_id)
        if data and data.refresh_token:
            await keycloak.logout(settings, data.refresh_token)
        sessions.delete(session_id)
    _clear_session_cookie(response)
    return response


@app.get("/api/reports")
async def reports(request: Request) -> Response:
    """Защищённый проксирующий эндпоинт.

    1. Проверяем сессию по cookie.
    2. При необходимости обновляем access_token по refresh_token.
    3. РОТИРУЕМ session id (перепривязка токенов к новому id) и обновляем cookie.
    4. Проксируем запрос в reports-api с Bearer access_token.
    """
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)

    data = sessions.get(session_id)
    if data is None:
        return JSONResponse({"error": "session expired"}, status_code=401)

    data = await _ensure_fresh_access(session_id, data)

    # Ротация сессии против session fixation: новый id на каждом защищённом запросе.
    new_session_id = sessions.rotate(session_id, data)

    upstream_body: dict
    upstream_status = 200
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.get(
                f"{settings.api_url}/reports",
                headers={"Authorization": f"Bearer {data.access_token}"},
            )
        upstream_status = upstream.status_code
        try:
            upstream_body = upstream.json()
        except ValueError:
            upstream_body = {"raw": upstream.text}
    except httpx.HTTPError:
        # reports-api в Задании 1 ещё заглушка — не роняем поток авторизации.
        upstream_status = 502
        upstream_body = {"error": "reports-api unavailable"}

    response = JSONResponse(
        {"session_id": new_session_id, "report": upstream_body},
        status_code=upstream_status,
    )
    _set_session_cookie(response, new_session_id)
    return response
