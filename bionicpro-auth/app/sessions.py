"""Хранилище сессий и токенов в оперативной памяти.

Требования задания:
- access_token и refresh_token хранятся только на сервере, в зашифрованном виде
  (Fernet), и НИКОГДА не передаются фронтенду;
- токены привязаны к идентификатору сессии;
- поддерживается ротация session id (защита от session fixation).

Хранилище процессное (in-memory): при рестарте сервиса сессии теряются, что для
учебного стенда допустимо. Для горизонтального масштабирования сюда подставляется
распределённый кеш (Redis) с тем же интерфейсом.
"""
import json
import time
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from .security import new_session_id


@dataclass
class SessionData:
    access_token: str
    refresh_token: str
    # Абсолютное время (unix) истечения access_token.
    access_expires_at: float
    sub: str = ""
    username: str = ""
    roles: list[str] = field(default_factory=list)
    # Абсолютное время истечения самой сессии.
    session_expires_at: float = 0.0


class SessionStore:
    """In-memory store. Значения токенов шифруются Fernet перед записью."""

    def __init__(self, fernet_key: str, session_ttl_seconds: int) -> None:
        key = fernet_key.encode() if fernet_key else Fernet.generate_key()
        self._fernet = Fernet(key)
        self._ttl = session_ttl_seconds
        # session_id -> зашифрованный blob с данными сессии
        self._store: dict[str, bytes] = {}

    # --- сериализация/шифрование ------------------------------------------
    def _encrypt(self, data: SessionData) -> bytes:
        payload = json.dumps(
            {
                "access_token": data.access_token,
                "refresh_token": data.refresh_token,
                "access_expires_at": data.access_expires_at,
                "sub": data.sub,
                "username": data.username,
                "roles": data.roles,
                "session_expires_at": data.session_expires_at,
            }
        ).encode("utf-8")
        return self._fernet.encrypt(payload)

    def _decrypt(self, blob: bytes) -> SessionData:
        payload = json.loads(self._fernet.decrypt(blob).decode("utf-8"))
        return SessionData(**payload)

    # --- операции ----------------------------------------------------------
    def create(self, data: SessionData) -> str:
        data.session_expires_at = time.time() + self._ttl
        session_id = new_session_id()
        self._store[session_id] = self._encrypt(data)
        return session_id

    def get(self, session_id: str) -> SessionData | None:
        blob = self._store.get(session_id)
        if blob is None:
            return None
        data = self._decrypt(blob)
        if data.session_expires_at < time.time():
            self.delete(session_id)
            return None
        return data

    def update(self, session_id: str, data: SessionData) -> None:
        if session_id in self._store:
            self._store[session_id] = self._encrypt(data)

    def rotate(self, old_session_id: str, data: SessionData) -> str:
        """Перепривязывает токены к НОВОМУ session id (против session fixation).

        Старый id уничтожается, выдаётся свежий. Время жизни сессии продлевается.
        """
        self.delete(old_session_id)
        data.session_expires_at = time.time() + self._ttl
        new_id = new_session_id()
        self._store[new_id] = self._encrypt(data)
        return new_id

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)


class TransientStore:
    """Краткоживущее хранилище данных авторизационного запроса (PKCE + state).

    Используется между /auth/login и /auth/callback. Ключ — state.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict]] = {}

    def put(self, key: str, value: dict) -> None:
        self._store[key] = (time.time() + self._ttl, value)

    def pop(self, key: str) -> dict | None:
        item = self._store.pop(key, None)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.time():
            return None
        return value
