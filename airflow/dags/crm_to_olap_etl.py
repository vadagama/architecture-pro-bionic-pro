"""ETL BionicPRO: CRM (PostgreSQL) → витрина отчётности (ClickHouse OLAP).

DAG объединяет данные телеметрии датчиков и справочник клиентов из CRM,
агрегирует телеметрию в разрезе (пользователь × день) и грузит результат в
витрину `bionicpro.user_reports`, из которой сервис reports-api отдаёт отчёты
без тяжёлых вычислений в реальном времени.

Расписание: ежедневно (@daily). Прогон идемпотентен — витрина на
ReplacingMergeTree(generated_at), повторная загрузка той же строки
(username, report_date) заменяется более свежей версией.

Связь с CRM/ClickHouse — через переменные окружения (заданы в docker-compose
для контейнеров Airflow).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import clickhouse_connect
import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator

# --- параметры подключения (из окружения) ---------------------------------
CRM_HOST = os.getenv("CRM_DB_HOST", "crm_db")
CRM_PORT = int(os.getenv("CRM_DB_PORT", "5432"))
CRM_DB = os.getenv("CRM_DB_NAME", "crm_db")
CRM_USER = os.getenv("CRM_DB_USER", "crm_user")
CRM_PASSWORD = os.getenv("CRM_DB_PASSWORD", "crm_password")

CH_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CH_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CH_DATABASE = os.getenv("CLICKHOUSE_DB", "bionicpro")

# Агрегация телеметрии в разрезе клиента и дня + атрибуты клиента из CRM.
# Группировка по username даёт строку отчёта на пользователя за каждый день.
EXTRACT_SQL = """
    SELECT
        c.username,
        t.event_time::date                              AS report_date,
        c.full_name,
        c.country,
        c.prosthesis_model,
        c.serial_number,
        COUNT(*)                                         AS total_sessions,
        ROUND(SUM(t.active_seconds) / 60.0, 2)          AS total_active_min,
        ROUND(AVG(t.response_ms), 2)                     AS avg_response_ms,
        MAX(t.response_ms)                               AS max_response_ms,
        ROUND(AVG(t.signal_quality), 3)                  AS avg_signal_quality,
        SUM(t.movements)                                 AS total_movements,
        ROUND(AVG(t.battery_pct), 2)                     AS avg_battery_pct
    FROM prosthesis_telemetry t
    JOIN clients c ON c.serial_number = t.serial_number
    GROUP BY c.username, t.event_time::date, c.full_name, c.country,
             c.prosthesis_model, c.serial_number
    ORDER BY c.username, report_date
"""

MART_COLUMNS = [
    "username", "report_date", "full_name", "country", "prosthesis_model",
    "serial_number", "total_sessions", "total_active_min", "avg_response_ms",
    "max_response_ms", "avg_signal_quality", "total_movements",
    "avg_battery_pct", "generated_at",
]


def extract_and_transform(**context) -> list:
    """E + T: вытащить телеметрию из CRM и агрегировать в строки витрины."""
    conn = psycopg2.connect(
        host=CRM_HOST, port=CRM_PORT, dbname=CRM_DB,
        user=CRM_USER, password=CRM_PASSWORD,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(EXTRACT_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    # Приводим к JSON-сериализуемому виду для XCom (date → ISO-строка).
    result = [
        [
            r[0], r[1].isoformat(), r[2], r[3], r[4], r[5],
            int(r[6]), float(r[7]), float(r[8]), int(r[9]),
            float(r[10]), int(r[11]), float(r[12]),
        ]
        for r in rows
    ]
    print(f"Извлечено и агрегировано строк витрины: {len(result)}")
    return result


def load_to_clickhouse(**context) -> None:
    """L: загрузить агрегаты в витрину ClickHouse (идемпотентно)."""
    ti = context["ti"]
    rows = ti.xcom_pull(task_ids="extract_and_transform")
    if not rows:
        print("Нет данных для загрузки — пропускаем.")
        return

    generated_at = context["logical_date"].strftime("%Y-%m-%d %H:%M:%S")

    client = clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username=CH_USER,
        password=CH_PASSWORD, database=CH_DATABASE,
    )

    # Дописываем версию строки (generated_at) и восстанавливаем date из ISO.
    data = []
    for r in rows:
        report_date = datetime.strptime(r[1], "%Y-%m-%d").date()
        data.append([
            r[0], report_date, r[2], r[3], r[4], r[5],
            r[6], r[7], r[8], r[9], r[10], r[11], r[12],
            datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S"),
        ])

    client.insert("user_reports", data, column_names=MART_COLUMNS)
    print(f"Загружено строк в bionicpro.user_reports: {len(data)}")


default_args = {
    "owner": "bionicpro",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="crm_to_olap_etl",
    description="ETL CRM → ClickHouse: витрина отчётности по пользователям",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule="@daily",          # расписание сбора данных и подготовки витрины
    catchup=False,
    max_active_runs=1,
    tags=["bionicpro", "etl", "reports"],
) as dag:

    extract = PythonOperator(
        task_id="extract_and_transform",
        python_callable=extract_and_transform,
    )

    load = PythonOperator(
        task_id="load_to_clickhouse",
        python_callable=load_to_clickhouse,
    )

    extract >> load
