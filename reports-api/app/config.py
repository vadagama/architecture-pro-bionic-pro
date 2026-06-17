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
    # Источник витрины. Задание 4: по умолчанию CDC-витрина user_reports_cdc
    # (наполняется потоком Debezium→Kafka→ClickHouse). Для возврата к витрине
    # Задания 2 (Airflow ETL) достаточно выставить REPORTS_CLICKHOUSE_SOURCE=user_reports.
    clickhouse_source: str = "user_reports_cdc"

    # Задание 3: S3 (Minio) + CDN для кэширования готовых отчётов.
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "bionicpro-reports"
    s3_region: str = "us-east-1"
    # Базовый публичный адрес CDN (Nginx), который видит браузер.
    cdn_public_base_url: str = "http://localhost:8090"
    # Секрет для HMAC-ключа объекта (capability-URL). В проде — из секрет-хранилища.
    report_url_secret: str = "bionicpro-report-secret-change-me"

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.realm}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
