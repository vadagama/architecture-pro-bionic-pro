-- Тестовые данные CRM. usernames совпадают с пользователями Keycloak realm
-- (см. keycloak/realm-export.json): user1, user2, prothetic1..3.

INSERT INTO clients (username, full_name, country, prosthesis_model, serial_number, purchase_date, data_collection_enabled) VALUES
    ('user1',      'Ivan Petrov',     'Russia',      'BionicArm X1',  'SN-X1-0001', CURRENT_DATE - INTERVAL '120 days', TRUE),
    ('user2',      'Maria Sidorova',  'Russia',      'BionicArm X2',  'SN-X2-0002', CURRENT_DATE - INTERVAL '90 days',  TRUE),
    ('prothetic1', 'John Doe',        'Kazakhstan',  'BionicLeg L1',  'SN-L1-0003', CURRENT_DATE - INTERVAL '200 days', TRUE),
    ('prothetic2', 'Jane Smith',      'Kazakhstan',  'BionicArm X1',  'SN-X1-0004', CURRENT_DATE - INTERVAL '45 days',  TRUE),
    ('prothetic3', 'Alex Johnson',    'Germany',     'BionicHand H1', 'SN-H1-0005', CURRENT_DATE - INTERVAL '15 days',  FALSE)
ON CONFLICT (username) DO NOTHING;

-- Генерируем телеметрию за последние 10 дней: ~24 записи в день на каждый протез
-- (по записи в час) с правдоподобными значениями. prothetic3 отключил сбор данных
-- (data_collection_enabled = FALSE) — для него телеметрию не пишем.
INSERT INTO prosthesis_telemetry (serial_number, event_time, response_ms, signal_quality, movements, battery_pct, active_seconds)
SELECT
    c.serial_number,
    (CURRENT_DATE - (d || ' days')::interval) + (h || ' hours')::interval AS event_time,
    60 + (random() * 70)::int                                   AS response_ms,      -- 60..130 мс
    round((0.80 + random() * 0.19)::numeric, 3)                 AS signal_quality,   -- 0.80..0.99
    (random() * 200)::int                                       AS movements,
    20 + (random() * 80)::int                                   AS battery_pct,
    (random() * 3600)::int                                      AS active_seconds
FROM clients c
CROSS JOIN generate_series(0, 9) AS d   -- день: 0..9 назад
CROSS JOIN generate_series(0, 23) AS h  -- час: 0..23
WHERE c.data_collection_enabled = TRUE;
