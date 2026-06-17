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

- Frontend: http://localhost:3000
- bionicpro-auth (BFF): http://localhost:8000
- Keycloak: http://localhost:8080 (admin/admin)
- OpenLDAP: localhost:389

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
