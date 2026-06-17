-- Задание 4: подготовка CRM-источника к CDC (Debezium, логическая репликация).
--
-- REPLICA IDENTITY FULL — в WAL пишется полный образ строки (а не только PK).
-- Это даёт Debezium корректный "before"-образ при UPDATE/DELETE, что нужно для
-- обработки удалений в ClickHouse (флаг __deleted). wal_level=logical задаётся
-- параметрами запуска postgres в docker-compose.
--
-- Скрипт идемпотентен и выполняется initdb на чистом томе CRM.

ALTER TABLE clients REPLICA IDENTITY FULL;
ALTER TABLE prosthesis_telemetry REPLICA IDENTITY FULL;
