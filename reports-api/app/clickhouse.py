"""Доступ к OLAP-витрине ClickHouse. Только чтение готовых агрегатов —
никаких тяжёлых вычислений в реальном времени.
"""
from typing import Optional

import clickhouse_connect

from .config import get_settings

settings = get_settings()

# Колонки витрины в порядке выборки (см. clickhouse/init/01_mart.sql).
_COLUMNS = [
    "report_date", "full_name", "country", "prosthesis_model", "serial_number",
    "total_sessions", "total_active_min", "avg_response_ms", "max_response_ms",
    "avg_signal_quality", "total_movements", "avg_battery_pct",
]


def _client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_db,
    )


def fetch_user_report(
    username: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list:
    """Строки витрины по конкретному пользователю.

    Фильтрация по username — на стороне запроса (параметризовано, без SQL-инъекций).
    Возвращаются только те периоды, что УЖЕ обработаны Airflow (присутствуют в
    витрине); будущих/необработанных дат в ответе быть не может по построению.
    FINAL схлопывает версии ReplacingMergeTree, отдавая последнюю по generated_at.
    """
    conditions = ["username = {username:String}"]
    params: dict = {"username": username}
    if date_from:
        conditions.append("report_date >= {date_from:Date}")
        params["date_from"] = date_from
    if date_to:
        conditions.append("report_date <= {date_to:Date}")
        params["date_to"] = date_to

    query = f"""
        SELECT {", ".join(_COLUMNS)}
        FROM user_reports FINAL
        WHERE {" AND ".join(conditions)}
        ORDER BY report_date
    """

    client = _client()
    result = client.query(query, parameters=params)
    return [dict(zip(_COLUMNS, row)) for row in result.result_rows]


def ping() -> bool:
    try:
        _client().query("SELECT 1")
        return True
    except Exception:
        return False
