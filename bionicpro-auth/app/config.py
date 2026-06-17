"""Конфигурация bionicpro-auth.

Все значения берутся из переменных окружения. Разделяем внутренний и публичный
URL Keycloak: внутренний используется для server-to-server обмена токенами
(контейнер ходит на keycloak:8080), публичный — для редиректа браузера на форму
логина (браузер ходит на localhost:8080).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    # Keycloak
    keycloak_internal_url: str = "http://keycloak:8080"
    keycloak_public_url: str = "http://localhost:8080"
    realm: str = "reports-realm"
    client_id: str = "bionicpro-auth"
    client_secret: str = "bionicpro-auth-secret-change-me"

    # OAuth endpoints / callbacks
    redirect_uri: str = "http://localhost:8000/auth/callback"
    frontend_url: str = "http://localhost:3000"

    # Downstream API (сервис отчётов; в Задании 1 — заглушка)
    api_url: str = "http://localhost:8000"

    # Сессии
    session_cookie_name: str = "bionicpro_session"
    # Время жизни сессии должно быть больше TTL access_token (120с в Keycloak),
    # чтобы успевать обновлять access_token через refresh_token.
    session_ttl_seconds: int = 1800
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    # Ключ шифрования токенов в памяти (Fernet). Если пуст — генерируется на старте.
    fernet_key: str = ""

    @property
    def realm_base_internal(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.realm}"

    @property
    def realm_base_public(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.realm}"

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.realm_base_public}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.realm_base_internal}/protocol/openid-connect/token"

    @property
    def logout_endpoint(self) -> str:
        return f"{self.realm_base_internal}/protocol/openid-connect/logout"


@lru_cache
def get_settings() -> Settings:
    return Settings()
