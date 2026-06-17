-- =============================================================================
-- Задание 4: CDC-путь CRM → Kafka → ClickHouse → витрина отчётности.
--
-- Назначение: снять с CRM (OLTP) нагрузку от массовых выгрузок. Вместо тяжёлых
-- батчевых SELECT'ов (Airflow, Задание 2) изменения CRM приходят потоком из
-- Kafka (их туда пишет Debezium, читая WAL логической репликацией).
--
-- Цепочка объектов:
--   kafka_clients / kafka_telemetry   — KafkaEngine, читают топики Debezium;
--   mv_clients / mv_telemetry         — MaterializedView, переливают поток
--                                       в landing-таблицы clients_raw / telemetry_raw;
--   mv_user_reports                   — MaterializedView, на вставку телеметрии
--                                       джойнит клиентов и пишет агрегаты витрины;
--   user_reports_agg                  — витрина (AggregatingMergeTree);
--   user_reports_cdc                  — VIEW-обёртка: финализирует агрегаты в те
--                                       же колонки, что витрина Задания 2.
--
-- Сосуществует с Заданием 2: таблица bionicpro.user_reports (Airflow) не трогается.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS bionicpro;

-- -----------------------------------------------------------------------------
-- 1. KafkaEngine: входные очереди из топиков Debezium.
--    Сообщения — плоский JSON (Debezium SMT ExtractNewRecordState, unwrap).
--    Имена колонок совпадают с ключами JSON; служебные поля __op/__ts_ms/__deleted
--    добавлены SMT (delete.handling.mode=rewrite, add.fields=op,ts_ms).
--    input_format_skip_unknown_fields=1 — игнорировать лишние ключи (напр. purchase_date).
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bionicpro.kafka_clients
(
    client_id               Int64,
    username                String,
    full_name               String,
    country                 String,
    prosthesis_model        String,
    serial_number           String,
    data_collection_enabled UInt8,
    `__op`                  String,
    `__ts_ms`               Int64,
    `__deleted`             String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm.public.clients',
    kafka_group_name = 'clickhouse_clients',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_handle_error_mode = 'stream',
    input_format_skip_unknown_fields = 1,
    date_time_input_format = 'best_effort';

CREATE TABLE IF NOT EXISTS bionicpro.kafka_telemetry
(
    id             Int64,
    serial_number  String,
    event_time     Int64,      -- epoch millis (Debezium time.precision.mode=connect)
    response_ms    Int32,
    signal_quality Float64,    -- NUMERIC → double (decimal.handling.mode=double)
    movements      Int32,
    battery_pct    Int32,
    active_seconds Int32,
    `__op`         String,
    `__ts_ms`      Int64,
    `__deleted`    String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm.public.prosthesis_telemetry',
    kafka_group_name = 'clickhouse_telemetry',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_handle_error_mode = 'stream',
    input_format_skip_unknown_fields = 1,
    date_time_input_format = 'best_effort';

-- -----------------------------------------------------------------------------
-- 2. Landing-таблицы (хранение потока).
--    clients_raw: ReplacingMergeTree(__ts_ms) — последняя версия клиента по
--    времени события CDC; ORDER BY serial_number (ключ джойна с телеметрией).
--    telemetry_raw: MergeTree, телеметрия в основном append-only.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bionicpro.clients_raw
(
    serial_number    String,
    username         String,
    full_name        String,
    country          String,
    prosthesis_model String,
    is_deleted       UInt8,
    `__ts_ms`        Int64
)
ENGINE = ReplacingMergeTree(`__ts_ms`)
ORDER BY serial_number;

CREATE TABLE IF NOT EXISTS bionicpro.telemetry_raw
(
    id             Int64,
    serial_number  String,
    event_time     DateTime,
    response_ms    Int32,
    signal_quality Float64,
    movements      Int32,
    battery_pct    Int32,
    active_seconds Int32,
    is_deleted     UInt8
)
ENGINE = MergeTree
ORDER BY (serial_number, event_time);

-- -----------------------------------------------------------------------------
-- 3. MaterializedView: Kafka-очередь → landing-таблицы.
--    __deleted приходит строкой 'true'/'false' (delete.handling.mode=rewrite).
-- -----------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.mv_clients
TO bionicpro.clients_raw AS
SELECT
    serial_number,
    username,
    full_name,
    country,
    prosthesis_model,
    if(`__deleted` = 'true', 1, 0) AS is_deleted,
    `__ts_ms`
FROM bionicpro.kafka_clients;

CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.mv_telemetry
TO bionicpro.telemetry_raw AS
SELECT
    id,
    serial_number,
    fromUnixTimestamp64Milli(event_time) AS event_time,
    response_ms,
    signal_quality,
    movements,
    battery_pct,
    active_seconds,
    if(`__deleted` = 'true', 1, 0) AS is_deleted
FROM bionicpro.kafka_telemetry;

-- -----------------------------------------------------------------------------
-- 4. Витрина отчётности (AggregatingMergeTree).
--    Гранулярность: (пользователь × день). SimpleAggregateFunction — частичные
--    агрегаты блоков суммируются при фоновом merge; средние хранятся как
--    sum + count (total_sessions) и финализируются в VIEW.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bionicpro.user_reports_agg
(
    username           String,
    report_date        Date,
    full_name          SimpleAggregateFunction(anyLast, String),
    country            SimpleAggregateFunction(anyLast, String),
    prosthesis_model   SimpleAggregateFunction(anyLast, String),
    serial_number      SimpleAggregateFunction(anyLast, String),
    total_sessions     SimpleAggregateFunction(sum, UInt64),
    total_active_sec   SimpleAggregateFunction(sum, UInt64),
    response_ms_sum    SimpleAggregateFunction(sum, UInt64),
    max_response_ms    SimpleAggregateFunction(max, UInt32),
    signal_quality_sum SimpleAggregateFunction(sum, Float64),
    total_movements    SimpleAggregateFunction(sum, UInt64),
    battery_pct_sum    SimpleAggregateFunction(sum, UInt64)
)
ENGINE = AggregatingMergeTree
ORDER BY (username, report_date);

-- -----------------------------------------------------------------------------
-- 5. MaterializedView витрины: триггерится на вставку в telemetry_raw, джойнит
--    свежий блок телеметрии с актуальными клиентами (clients_raw FINAL) и пишет
--    частичные агрегаты в user_reports_agg.
--    INNER JOIN: телеметрия без известного клиента в витрину не попадает.
-- -----------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS bionicpro.mv_user_reports
TO bionicpro.user_reports_agg AS
SELECT
    c.username                 AS username,
    toDate(t.event_time)       AS report_date,
    c.full_name                AS full_name,
    c.country                  AS country,
    c.prosthesis_model         AS prosthesis_model,
    t.serial_number            AS serial_number,
    count()                    AS total_sessions,
    sum(t.active_seconds)      AS total_active_sec,
    sum(t.response_ms)         AS response_ms_sum,
    max(t.response_ms)         AS max_response_ms,
    sum(t.signal_quality)      AS signal_quality_sum,
    sum(t.movements)           AS total_movements,
    sum(t.battery_pct)         AS battery_pct_sum
FROM bionicpro.telemetry_raw AS t
INNER JOIN
(
    SELECT serial_number, username, full_name, country, prosthesis_model
    FROM bionicpro.clients_raw FINAL
    WHERE is_deleted = 0
) AS c ON c.serial_number = t.serial_number
WHERE t.is_deleted = 0
GROUP BY
    c.username, toDate(t.event_time), c.full_name, c.country,
    c.prosthesis_model, t.serial_number;

-- -----------------------------------------------------------------------------
-- 6. VIEW-обёртка: финализирует агрегаты витрины в КОЛОНКИ, идентичные витрине
--    Задания 2 (bionicpro.user_reports). reports-api переключается на этот VIEW
--    без изменения формата ответа. avg = sum / total_sessions.
-- -----------------------------------------------------------------------------

CREATE VIEW IF NOT EXISTS bionicpro.user_reports_cdc AS
SELECT
    username,
    report_date,
    anyLast(full_name)                                          AS full_name,
    anyLast(country)                                            AS country,
    anyLast(prosthesis_model)                                   AS prosthesis_model,
    anyLast(serial_number)                                      AS serial_number,
    sum(total_sessions)                                         AS total_sessions,
    round(sum(total_active_sec) / 60.0, 2)                      AS total_active_min,
    round(sum(response_ms_sum) / sum(total_sessions), 2)        AS avg_response_ms,
    max(max_response_ms)                                        AS max_response_ms,
    round(sum(signal_quality_sum) / sum(total_sessions), 3)     AS avg_signal_quality,
    sum(total_movements)                                        AS total_movements,
    round(sum(battery_pct_sum) / sum(total_sessions), 2)        AS avg_battery_pct
FROM bionicpro.user_reports_agg
GROUP BY username, report_date;
