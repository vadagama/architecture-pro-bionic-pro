-- CRM BionicPRO — источник данных для ETL (Задание 2).
-- Две таблицы-источника, которые объединяет Airflow:
--   clients              — справочник клиентов (CRM);
--   prosthesis_telemetry — сырая телеметрия с датчиков протеза ("DB" с сигналами).
-- username в clients совпадает с preferred_username в Keycloak — по нему reports-api
-- ограничивает доступ "только свой отчёт".

CREATE TABLE IF NOT EXISTS clients (
    client_id               SERIAL PRIMARY KEY,
    username                VARCHAR(255) UNIQUE NOT NULL,
    full_name               VARCHAR(255) NOT NULL,
    country                 VARCHAR(64)  NOT NULL,
    prosthesis_model        VARCHAR(64)  NOT NULL,
    serial_number           VARCHAR(64)  UNIQUE NOT NULL,
    purchase_date           DATE         NOT NULL,
    data_collection_enabled BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS prosthesis_telemetry (
    id             BIGSERIAL PRIMARY KEY,
    serial_number  VARCHAR(64) NOT NULL REFERENCES clients (serial_number),
    event_time     TIMESTAMP   NOT NULL,
    response_ms    INTEGER     NOT NULL,   -- скорость реагирования протеза, мс
    signal_quality NUMERIC(4,3) NOT NULL,  -- качество миосигнала, 0..1
    movements      INTEGER     NOT NULL,   -- распознанных движений за интервал
    battery_pct    INTEGER     NOT NULL,   -- заряд батареи, %
    active_seconds INTEGER     NOT NULL    -- секунд активности за интервал
);

-- Индекс для оконной выборки телеметрии в ETL.
CREATE INDEX IF NOT EXISTS idx_telemetry_serial_time
    ON prosthesis_telemetry (serial_number, event_time);
