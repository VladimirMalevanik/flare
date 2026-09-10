# Flare backend

FastAPI, PostgreSQL и workspace RLS. Поддерживаются регистрация, вход,
серверные сессии и сохранение текстовых заметок.

## Запуск

Из `backend/`, после настройки подключений из корневого `.env.example`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
export FLARE_ENV=development
export FLARE_DEV_MODE=false
export CORS_ORIGINS=http://localhost:3000
uvicorn app.main:app --reload
```

Frontend использует `/api` через same-origin Next.js rewrite.
`API_INTERNAL_URL` должен указывать на backend при сборке и запуске Next.js.
В production обязательны `FLARE_ENV=production`, `DATABASE_URL`, точный
HTTPS frontend origin в `CORS_ORIGINS` и TLS на внешнем входе. Runtime БД —
только `flare_app`, без SUPERUSER/BYPASSRLS. Миграции выполняются отдельным
владельцем. В self-managed PostgreSQL миграции создают выделенные NOLOGIN-роли
`flare_onboarding` и `flare_job_executor`, а также worker-роль. В Yandex Managed
PostgreSQL пользователи `flare_owner`, `flare_app`, `flare_worker` создаются
через Yandex Cloud, SECURITY DEFINER-функции принадлежат `flare_owner`, а его
`MIGRATION_DATABASE_URL` не передаётся API или worker. Для этого используются
отдельные `.env.yandex.migrate`, `.env.yandex.api` и `.env.yandex.worker`, а
нужный файл выбирается через `FLARE_DOTENV_PATH`. Пошаговая настройка:
[docs/yandex-managed-postgresql.md](docs/yandex-managed-postgresql.md).

## HTTP-контракт

Все state-changing запросы, включая curl/Swagger, должны передавать точный
разрешённый `Origin`. Credentials — cookie, без клиентских user/workspace headers.

| Endpoint | JSON / результат |
| --- | --- |
| `POST /auth/register` | `{email, password, name}` → 201, cookie; один workspace с ролью owner |
| `POST /auth/login` | `{email, password}` → 200, новая cookie |
| `POST /auth/logout` | → 204, отзыв текущей сессии и удаление cookie |
| `GET /auth/me` | `{user: {id, email, name}, workspace: {id, name, role}}` |
| `POST /items` | `{type: "note", content, title?}` → документ, готовая версия и chunk |
| `GET /items` | Поиск: `query`, `type`, `limit` |
| `GET /items/{id}` | Активная заметка своего workspace |
| `DELETE /items/{id}` | Soft delete; опубликованная версия и chunk сохраняются |

Пароль при регистрации: 12–128 символов; имя: 1–100. Email обрезается по краям
и приводится к нижнему регистру. Ошибки: 401 — нет действующей сессии/неверный
вход; 403 — Origin, membership или роль; 404 — чужой/отсутствующий item;
409 — регистрация не завершена (включая занятый email); 422 — неверный payload.
Ответы auth/items имеют `Cache-Control: no-store`; ошибки валидации не отражают пароль.

## Сессии и авторизация

Пароли хешируются Argon2id (`pwdlib[argon2]`). Cookie содержит случайный
256-битный opaque token; БД хранит только детерминированный SHA-256 digest.
Cookie: HttpOnly, SameSite=Lax, Path=/, без Domain; в production — Secure и
имя `__Host-flare_session`, локально — `flare_session`. Успешный повторный вход
отзывает прежнюю сессию этого браузера; logout отзывает текущую. Другие
устройства сохраняют свои сессии.

`SESSION_LIFETIME_SECONDS=604800` задаёт абсолютный срок 7 дней,
`SESSION_IDLE_SECONDS=86400` — 24 часа простоя. Каждый authenticated request
проверяет срок, отзыв, disabled user и membership, затем обновляет last_seen.
Истечение не продлевает абсолютный срок. Item-транзакция повторно проверяет
membership/роль; RLS получает transaction-local `app.user_id` и `app.workspace_id`.

Миграция `0004` добавляет auth_users/auth_sessions, сохраняя старые строковые
`workspace_members.user_id` без конвертации и без FK на auth_users. Новые ID —
`auth:<uuid>`. Legacy memberships сохраняются, но автоматически не присваиваются
новым аккаунтам. Перенос старой учётной записи требует отдельного проверенного
сопоставления. Регистрация атомарно создаёт user/workspace/owner/session;
конфликт email откатывает всё. Runtime не может напрямую менять memberships:
узкая SECURITY DEFINER-функция создаёт только новый workspace с владельцем.
Restrictive RLS дополнительно проверяет пользователя и writer-role.

## Локальный dev mode

Только при `FLARE_ENV=development` или `test` можно явно задать
`FLARE_DEV_MODE=true` и все `FLARE_DEV_WORKSPACE_ID`, `FLARE_DEV_USER_ID`,
`FLARE_DEV_WORKSPACE_NAME`. Это серверная фиксированная identity. Предъявленная
невалидная auth cookie или Authorization никогда не переключает запрос в dev.
Production с включённым dev mode не запускается. Frontend mock mode также
доступен только в development при явном `NEXT_PUBLIC_DATA_PROVIDER=mock`.

## Ограничения безопасности и эксплуатации

Auth-таблицы доступны только серверной DB-роли, без tenant RLS: backend должен
искать сессию до определения workspace. RLS доверяет установленной сервером
identity и не защищает от компрометации backend/DB credentials. Не выдавайте
клиенту доступ к БД и не логируйте пароли, Cookie или Set-Cookie.

В этом блоке нет email verification, reset, OAuth, invitations, лимитера входа,
автоматической очистки истёкших сессий или списка устройств. Перед открытым
публичным запуском нужны ограничения частоты входа/регистрации на внешнем
входе и эксплуатационный процесс очистки сессий. Ответ 409 позволяет определить
занятость email. Настройки профиля в UI доступны только для чтения; account
editing не реализован. TLS/reverse-proxy deployment проверяется отдельно от
локальной валидации. Не используйте локальный HTTP-режим в production.

Схема: [docs/database.md](docs/database.md). Слои:
[docs/architecture.md](docs/architecture.md). Проверки:
`pytest -q backend/tests` из корня с `DATABASE_URL` роли flare_app и
`TEST_DATABASE_URL` администратора одноразовой мигрированной PostgreSQL с pgvector.

## Изолированный AI-анализ (Block 2)

Добавлен async-анализ уже авторизованных `Evidence[]` через Groq 20B.
Он не подключён к API, сохранению Notes или БД. Контракт, ограничения, ошибки
и ручной smoke: [docs/text-analysis.md](docs/text-analysis.md).

## Durable jobs (Block 3)

Добавлен внутренний enqueue и отдельный PostgreSQL worker для анализа immutable
chunks. API сохранения Notes не запускает анализ. Схема 0005, роли, настройка,
команда запуска и проверки: [docs/analysis-jobs.md](docs/analysis-jobs.md).

### Block 4: persisted Flares

Migration 0006 adds a separate durable generation stage after completed analysis.
The same worker alternates extraction/generation attempts. Authenticated
`GET /flares` and `GET /flares/{id}` expose typed, evidence-backed records.
No Analyze trigger or automatic Note processing is added.
See [generation configuration, security and checks](docs/flare-generation.md).
