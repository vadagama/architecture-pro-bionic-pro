-- OLAP-витрина отчётности BionicPRO (Задание 2).
-- Заполняется Airflow DAG `crm_to_olap_etl`. Сервис reports-api читает её
-- БЕЗ тяжёлых вычислений в реальном времени.
--
-- Гранулярность: одна строка = (пользователь, день). Телеметрия датчиков уже
-- агрегирована в разрезе клиента, к ней приклеены атрибуты клиента из CRM.
--
-- ENGINE = ReplacingMergeTree(generated_at): повторный прогон ETL за тот же день
-- идемпотентно заменяет строку более свежей версией (по generated_at).
-- ORDER BY (username, report_date): первичный ключ начинается с username —
-- выборка "отчёт по конкретному пользователю" читает узкий диапазон, что и есть
-- быстрый доступ по пользователю.

CREATE DATABASE IF NOT EXISTS bionicpro;

CREATE TABLE IF NOT EXISTS bionicpro.user_reports
(
    username           String,
    report_date        Date,
    full_name          String,
    country            String,
    prosthesis_model   String,
    serial_number      String,
    total_sessions     UInt32,   -- число интервалов телеметрии за день
    total_active_min   Float64,  -- суммарная активность, минуты
    avg_response_ms    Float64,  -- средняя скорость реагирования
    max_response_ms    UInt32,   -- худшая (максимальная) скорость реагирования
    avg_signal_quality Float64,  -- среднее качество миосигнала
    total_movements    UInt64,   -- всего распознанных движений
    avg_battery_pct    Float64,  -- средний заряд батареи
    generated_at       DateTime  -- момент формирования строки (версия для Replacing)
)
ENGINE = ReplacingMergeTree(generated_at)
ORDER BY (username, report_date);
