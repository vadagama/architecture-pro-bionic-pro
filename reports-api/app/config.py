"""Конфигурация reports-api. Значения — из переменных окружения (префикс REPORTS_)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REPORTS_", extra="ignore")

    # Keycloak (resource server). Issuer access_token'а равен URL, по которому
    # bionicpro-auth обменивал код на токены — это ВНУТРЕННИЙ адрес keycloak:8080.
    keycloak_internal_url: str = "http://keycloak:8080"
    realm: str = "reports-realm"
    # Ожидаемый audience. Keycloak по умолчанию кладёт в aud "account"; если у
    # клиента reports-api настроен audience-mapper — укажите "reports-api".
    # Пустая строка отключает строгую проверку aud (подпись и issuer проверяются).
    expected_audience: str = ""

    # ClickHouse (OLAP-витрина)
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_db: str = "bionicpro"

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.realm}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
