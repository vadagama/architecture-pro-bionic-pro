# BionicPRO — проектная работа

- [Задание 1: повышение безопасности](#bionicpro--задание-1-повышение-безопасности)
- [Задание 2: сервис отчётов](#задание-2--сервис-отчётов)

---

# BionicPRO — Задание 1: повышение безопасности

Реализация усиления безопасности SSO для системы BionicPRO. Ключевой приём —
паттерн **BFF (Backend-for-Frontend / Token Handler)**: фронтенд перестаёт быть
OAuth-клиентом и не работает с токенами напрямую; вместо этого вводится
конфиденциальный бэкенд `bionicpro-auth`, который выполняет Authorization Code +
PKCE, хранит токены у себя и отдаёт фронту только сессионную cookie.

## Архитектура

```
Браузер (React SPA) ──session cookie (HTTP-only, Secure)──► bionicpro-auth (BFF)
                                                                │ Auth Code + PKCE (S256)
                                                                ▼
                                                            Keycloak (IdP / Broker)
                                                                ├─ User Federation → OpenLDAP (страна представительства)
                                                                ├─ Identity Brokering → Яндекс ID
                                                                └─ OTP (MFA, обязателен для всех)
```

C4-диаграмма контейнеров — в [scheme.drawio](scheme.drawio).

## Что сделано (по подзадачам Задания 1)

| # | Подзадача | Где |
|---|-----------|-----|
| 1 | C4-диаграмма управления учётными данными | `scheme.drawio` |
| 2 | PKCE (S256) вместо Code Grant | `bionicpro-auth` + клиент `bionicpro-auth` в realm |
| 3 | BFF: получение/хранение токенов, сессии, ротация | `bionicpro-auth/` |
| 4 | LDAP (OpenLDAP) + федерация + маппинг ролей | `docker-compose.yaml`, `ldap/`, realm component |
| 5 | MFA (OTP, обязателен) | realm: `CONFIGURE_TOTP` defaultAction |
| 6 | OAuth 2.0 Яндекс ID (Identity Brokering) | realm: identityProvider `yandex` |

Итоговый экспорт realm — `keycloak/keycloak-results-export.json`.

### Безопасная схема токенов (подзадача 3)

- `access_token` TTL = **120 с** (≤ 2 мин), задаётся в realm и на клиенте.
- Время жизни сессии = 1800 с (> TTL access_token) — успеваем обновлять по refresh.
- `access_token` и `refresh_token` **никогда не отдаются фронту**: хранятся в памяти
  BFF в зашифрованном виде (Fernet), привязаны к `session_id`.
- Фронту отдаётся **только** сессионная cookie с флагами **HTTP-only** и **Secure**.
- При истёкшем `access_token` BFF сам обновляет его по `refresh_token`.
- **Ротация сессии**: при каждом обращении к защищённому ресурсу (`/api/reports`)
  токены перепривязываются к новому `session_id`, cookie обновляется, новый
  `session_id` возвращается фронту (защита от session fixation).

Эндпоинты BFF: `GET /auth/login`, `GET /auth/callback`, `GET /auth/me`,
`POST /auth/logout`, `GET /api/reports`, `GET /health`.

## Запуск

```bash
docker compose up --build
```

- Frontend: http://localhost:3002
- bionicpro-auth (BFF): http://localhost:8000
- Keycloak: http://localhost:8082 (admin/admin)
- OpenLDAP: localhost:389

> Порты Keycloak (8082) и frontend (3002) смещены относительно стандартных
> 8080/3000, чтобы не конфликтовать с другими локальными сервисами. Меняются в
> `docker-compose.yaml` (`keycloak.ports`, `frontend.ports`) вместе с
> `AUTH_KEYCLOAK_PUBLIC_URL` и `AUTH_FRONTEND_URL` сервиса `bionicpro-auth`.

Тестовые пользователи realm: `user1/password123`, `prothetic1/prothetic123`,
`admin1/admin123`. Пользователи LDAP: `john.doe`, `jane.smith`, `alex.johnson`
(пароль `password`). При первом входе Keycloak потребует настроить OTP
(Google Authenticator / FreeOTP).

## Конфигурация Яндекс ID

В `keycloak/realm-export.json` IdP `yandex` использует плейсхолдеры
`${YANDEX_CLIENT_ID}` и `${YANDEX_CLIENT_SECRET}`. Перед использованием подставьте
реальные значения из зарегистрированного приложения Yandex OAuth.

## Замечания для продакшена

- В `docker-compose.yaml` для локального http-стенда `AUTH_COOKIE_SECURE=false`.
  В проде (https) выставьте `AUTH_COOKIE_SECURE=true`; для разных доменов фронта и
  BFF потребуется `SameSite=None; Secure` (см. `app/config.py`).
- `osixia/openldap` применяет `ldap/config.ldif` только при первой инициализации
  (пустой volume). При изменении ldif удалите данные контейнера openldap.
- Хранилище сессий — in-memory (процессное): при рестарте BFF сессии теряются, и
  оно не масштабируется горизонтально. Для прода замените `SessionStore` на
  распределённый кеш (Redis) с тем же интерфейсом.
- Параллельные запросы к `/api/reports` с одной cookie конкурируют за ротацию
  session_id (старый id удаляется сразу) — для учебного стенда с одной кнопкой
  это некритично.
- Секреты (`client_secret`, пароли) захардкожены для локального стенда; в проде —
  вынести в секрет-менеджер.

---

# Задание 2 — сервис отчётов

Пользователь скачивает отчёт о работе своего протеза. Данные собираются
ETL-процессом (**Apache Airflow**) из CRM и телеметрии датчиков, складываются в
витрину **OLAP (ClickHouse)**; бэкенд `reports-api` отдаёт готовый отчёт **только
по самому пользователю**.

## Архитектура (поток данных)

```
CRM clients (PostgreSQL) ─┐
                          ├─► Airflow DAG (ETL, @daily) ─► ClickHouse: bionicpro.user_reports (OLAP-витрина)
Телеметрия (PostgreSQL) ──┘                                          │
                                                                     ▼
Браузер ─cookie─► bionicpro-auth (BFF) ─Bearer JWT─► reports-api ─SQL по username─► ClickHouse
```

C4-диаграмма — в [scheme.drawio](scheme.drawio) (узлы `reports-api`, `Airflow (ETL)`,
`OLAP-витрина отчётности`).

## Что сделано (по подзадачам Задания 2)

| # | Подзадача | Где |
|---|-----------|-----|
| 1 | Архитектура подготовки/получения отчётов (ETL → OLAP → API) | `scheme.drawio` |
| 2 | Airflow DAG (ETL CRM→OLAP) + расписание | `airflow/dags/crm_to_olap_etl.py` |
| 2 | Витрина отчётности (агрегаты по пользователю) | `clickhouse/init/01_mart.sql` |
| 3 | Бэкенд API `/reports` из OLAP | `reports-api/` |
| 4 | Ограничение доступа: только свой отчёт | `reports-api/app/auth.py`, `main.py` |
| 5 | Кнопка получения отчёта в UI | `frontend/src/components/ReportPage.tsx` |

## Источники данных (CRM)

`crm/init/01_schema.sql` + `02_seed.sql` создают в PostgreSQL `crm_db`:

- `clients` — справочник клиентов (`username` совпадает с пользователями Keycloak:
  `user1`, `user2`, `prothetic1..3`);
- `prosthesis_telemetry` — сырая телеметрия датчиков за последние ~10 дней
  (по записи в час). `prothetic3` отключил сбор данных → телеметрии нет.

## Витрина OLAP (ClickHouse)

`bionicpro.user_reports` — `ReplacingMergeTree(generated_at)`,
`ORDER BY (username, report_date)`. Первичный ключ начинается с `username`, поэтому
выборка отчёта по пользователю читает узкий диапазон — **быстрый доступ**.
`ReplacingMergeTree` делает повторный прогон ETL за тот же день идемпотентным.

## ETL (Airflow DAG `crm_to_olap_etl`)

- `extract_and_transform`: вытаскивает телеметрию из CRM и агрегирует в разрезе
  (пользователь × день), приклеивает атрибуты клиента;
- `load_to_clickhouse`: грузит агрегаты в витрину;
- расписание `@daily`, `catchup=False`, идемпотентно (ReplacingMergeTree).

## reports-api (Python, FastAPI)

- `GET /reports` — валидация JWT (RS256-подпись по JWKS Keycloak + issuer),
  `username` берётся **строго из проверенного токена** (нельзя запросить чужой
  отчёт), запрос в ClickHouse фильтруется по этому `username`. Опциональные
  `?from=&to=` ограничивают период. Неаутентифицированный → 401.
- В витрине только периоды, **уже обработанные Airflow** — будущих/необработанных
  дат в ответе быть не может по построению.
- `GET /health` — статус + доступность ClickHouse.

Сервис — bearer-only resource server (клиент `reports-api` в realm). Токен ему
подставляет BFF (`bionicpro-auth` проксирует `/api/reports` → `reports-api:8000/reports`
с `Authorization: Bearer`).

## Запуск (дополнительно к Заданию 1)

```bash
docker compose up --build
```

- reports-api: http://localhost:8001 (внутри сети — `reports-api:8000`)
- ClickHouse: http://localhost:8123 (HTTP), localhost:9000 (native)
- CRM PostgreSQL: localhost:5434
- Airflow UI: http://localhost:8081 (admin/admin)

После старта зайдите в Airflow UI, включите (unpause) DAG `crm_to_olap_etl` и
запустите его — витрина наполнится. Затем в UI фронтенда (http://localhost:3002)
нажмите «Получить отчёт».

## Чек-лист задания

- UI вызывает API генерации отчётов — кнопка «Получить отчёт» → `/api/reports`. ✓
- Неаутентифицированный не может сгенерировать отчёт — 401 без валидной сессии/JWT. ✓
- Авторизованный получает только собственный отчёт — `username` из токена. ✓
- Отчёты берутся из OLAP (ClickHouse), без вычислений в реальном времени. ✓
- Только обработанные Airflow периоды — в витрине нет необработанных дат. ✓
