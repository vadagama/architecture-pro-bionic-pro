"""Доступ к OLAP-витрине ClickHouse. Только чтение готовых агрегатов —
никаких тяжёлых вычислений в реальном времени.
"""
from typing import Optional

import clickhouse_connect

from .config import get_settings

settings = get_settings()

# Колонки витрины в порядке выборки. Контракт одинаков для обеих витрин:
#   user_reports     — витрина Задания 2 (Airflow ETL, ReplacingMergeTree);
#   user_reports_cdc — VIEW Задания 4 над CDC-витриной (Debezium→Kafka→ClickHouse).
_COLUMNS = [
    "report_date", "full_name", "country", "prosthesis_model", "serial_number",
    "total_sessions", "total_active_min", "avg_response_ms", "max_response_ms",
    "avg_signal_quality", "total_movements", "avg_battery_pct",
]

# Источник из конфигурации — подставляется в FROM, поэтому валидируем как
# простой идентификатор (только латиница/цифры/подчёркивание), без инъекций.
def _source() -> str:
    name = settings.clickhouse_source
    if not name.replace("_", "").isalnum():
        raise ValueError(f"Недопустимое имя источника витрины: {name!r}")
    return name


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
    Возвращаются только те периоды, что УЖЕ присутствуют в витрине (обработаны
    ETL/CDC); будущих/необработанных дат в ответе быть не может по построению.
    Источник (user_reports_cdc / user_reports) уже отдаёт финализированные строки,
    поэтому FINAL не требуется.
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
        FROM {_source()}
        WHERE {" AND ".join(conditions)}
        ORDER BY report_date
    """

    client = _client()
    result = client.query(query, parameters=params)
    return [dict(zip(_COLUMNS, row)) for row in result.result_rows]


def fetch_report_meta(
    username: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Optional[dict]:
    """Лёгкий probe версии отчёта (Задание 3) — без выгрузки самих строк.

    Возвращает {"periods", "version"} либо None, если данных нет. version —
    компактный хеш по (max(report_date), sum(total_sessions), sum(total_movements)):
    меняется при появлении новых данных, поэтому годится как версия кэша. Запрос
    дешёвый (агрегаты по узкому диапазону пользователя), в отличие от выгрузки
    полного отчёта.
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
        SELECT
            count() AS periods,
            toString(cityHash64(
                toString(max(report_date)),
                sum(total_sessions),
                sum(total_movements)
            )) AS version
        FROM {_source()}
        WHERE {" AND ".join(conditions)}
    """

    result = _client().query(query, parameters=params)
    row = result.result_rows[0]
    periods = int(row[0])
    if periods == 0:
        return None
    return {"periods": periods, "version": row[1]}


def ping() -> bool:
    try:
        _client().query("SELECT 1")
        return True
    except Exception:
        return False
