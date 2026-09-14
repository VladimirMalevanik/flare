# Проект БД Flare

## Решение для MVP

PostgreSQL — основная БД, очередь durable jobs и граница workspace isolation.
pgvector установлен, а `chunks.embedding` сохраняет будущую vector capacity, но
текущий Analyze flow использует bounded recent Notes и keyword signals без
embeddings. Durable file/object storage в текущем runtime не подключён.

Источники: [pgvector](https://github.com/pgvector/pgvector), [PostgreSQL RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html), [psycopg](https://www.psycopg.org/psycopg3/docs/basic/usage.html).

## Сущности

| Таблица | Назначение |
| --- | --- |
| `workspaces` | Стартап/команда; граница доступа ко всем материалам |
| `workspace_members` | Пользователь и роль owner/editor/viewer в команде |
| `auth_users`, `auth_sessions` | Пользователи и отзываемые opaque sessions |
| `auth_email_verifications` | Одноразовые digest-токены подтверждения email |
| `documents` | Постоянная карточка материала и указатель на актуальную версию |
| `document_versions` | Снимок исходника: хеш, ключ файла, версия парсера, состояние обработки |
| `chunks` | Текст фрагмента, порядок, страница/раздел/таймкод в `locator`, embedding и имя модели |
| `analysis_jobs`, `analysis_job_sources` | Durable extraction job и pinned immutable sources |
| `analysis_runs` | Public idempotent Analyze status |
| `flare_generation_runs` | Durable Flare generation stage |
| `insights` | Текст вывода, модель и версия промпта для воспроизводимости |
| `insight_sources` | Связь инсайта с конкретными фрагментами и сохранённая цитата |
| `github_connection_states` | Workspace/user-bound одноразовый GitHub state |
| `github_connections` | GitHub installation и один выбранный repository на workspace |
| `import_batches` | Idempotent status bounded CSV/TXT/Markdown imports |
| `activity_events` | Allowlisted product/operations telemetry без текста источников |

`auth_users` хранит Argon2id password hash. Случайные session и email-verification
tokens в БД представлены только SHA-256 digest. `metadata`/`locator` в JSONB
подходят для дополнительных атрибутов, но принадлежность workspace и ключевые
связи остаются обычными колонками с ограничениями.

## Как проходит документ

1. API проверяет session, verified-user boundary, membership и write role.
2. Для Note/item path одна транзакция создаёт `documents`, ready
   `document_versions`, immutable `chunks` и переключает `current_version_id`.
   Text import также атомарно создаёт `import_batches` и bounded chunks; одинаковый
   активный content hash deduplicated в workspace. Запись источника не запускает ИИ.
3. `POST /analyze` отдельно выбирает ready chunks и атомарно сохраняет
   `analysis_runs`, `analysis_jobs` и `analysis_job_sources`.
4. Worker обрабатывает pinned chunks и записывает результат, не удерживая DB
   connection во время Groq call.
5. Успешная extraction stage создаёт `flare_generation_runs`; validated Flares и
   exact evidence сохраняются в `insights`/`insight_sources` одной транзакцией.

`PATCH /items/{id}` принимает `expectedCurrentVersionId`, блокирует документ и
публикует новую версию с номером N+1. Устаревший токен получает 409 и не может
затереть параллельную правку. `updated_at` меняется на уровне БД. Старые версии и
chunks остаются неизменяемыми. `import_batches.document_version_id` указывает на
точный импортированный snapshot; после замены или soft-delete batch остаётся в
истории, но перестаёт блокировать повторный импорт тех же байтов.

Опубликованные версии и chunks защищены от обычной перезаписи. Job claim использует
lease owner/token/expiry; bounded retry scheduling восстанавливает работу после
worker crash. Analyze idempotency key исключает duplicate logical runs.

## Поиск и источники

Vault выполняет текстовый поиск текущих ready-версий активных документов. Analyze
просматривает до 200 recent Notes и выбирает bounded chunks через deterministic
signals; vector retrieval не используется.

В начальной схеме `vector(1536)` — временная размерность, а не выбранный поставщик модели. Перед первой реальной индексацией нужно выбрать модель и размерность, обновить схему при необходимости. Равная размерность не делает разные модели совместимыми: запрос обязан фильтровать `embedding_model`. Миграция модели потребует пересчёта embeddings; не смешивайте их в одном поиске.

ИИ получает текст и ID pinned chunks. Сервер принимает citations только из этого
набора, проверяет exact quote, workspace и current source state, затем сохраняет
`insights` + `insight_sources` в одной транзакции. Valid empty output разрешён.

Инсайт хранит ссылки на конкретные chunks. При `deleted_at` документ исключается из
Vault и новые Analyze runs; Flare read query скрывает весь Flare, если supporting
document удалён или version перестала быть ready. Физическая retention/cleanup
policy для soft-deleted history пока не реализована.

## Изоляция команд

Каждая таблица данных содержит `workspace_id`. Составные внешние ключи не дают связать, например, инсайт команды A с chunk команды B. RLS ограничивает и чтение, и запись; без контекста команды данные недоступны роли приложения.

Контекст задаётся сервером **после** проверки подлинности пользователя и членства в команде, только на время транзакции:

```python
with connection.transaction():
    # workspace_id уже проверен сервером по текущему пользователю.
    connection.execute(
        "SELECT set_config('app.workspace_id', %s, true), set_config('app.user_id', %s, true)",
        (str(workspace_id), user_id),
    )
    # Все запросы этой операции выполняются здесь.
```

Параметр `true` делает настройку локальной для транзакции; после commit/rollback она не должна переходить следующему пользователю соединения. Используются параметры запроса, а не склейка SQL-строк.

**RLS с таким контекстом доверяет серверу.** Клиент не получает DB credentials
и не задаёт user/workspace identity. Сессия определяет оба ID; membership
проверяется внутри каждой item-транзакции. Restrictive policies проверяют
пользователя даже при ошибочно выбранном workspace; запись доступна owner/editor.

API подключается только ролью `flare_app`, без SUPERUSER/BYPASSRLS и владения
таблицами. Отдельный владелец применяет миграции. `0004` добавляет `auth_users`
и `auth_sessions`, не переписывая старые membership IDs и миграции. Auth-таблицы
доступны backend для входа до определения tenant. Новый workspace создаётся
узкой SECURITY DEFINER-функцией. В self-managed PostgreSQL функцией владеет
отдельная NOLOGIN-роль; в Yandex Managed PostgreSQL — `flare_owner`, чья строка
подключения используется только для миграций и не передаётся runtime. Прямые
изменения workspaces/memberships у runtime отозваны. Функция не позволяет
присоединиться к существующему workspace. Подробности и ограничения — в
[README](../README.md#сессии-и-авторизация), настройка облачной базы — в
[инструкции по Yandex Managed PostgreSQL](yandex-managed-postgresql.md).

## Границы первого этапа

Схема предполагает общий доступ участников ко всем материалам своего workspace.
Права на отдельный документ, workspace switching/invitations, чат, биллинг и граф
знаний не реализованы. GitHub connection metadata включены; GitHub activity
ingestion, URL fetching, binary file/audio ingestion и quota accounting не включены.

Изменения опубликованной схемы оформляйте новыми миграциями. `db/schema.sql`
принадлежит `0001` и после публикации не переписывается. Текущая linear chain:
`0001` → `0002` → `0003` → `0004` → `0005` → `0006` → `0007` → `0008`
→ `0009` → `0010` → `0011` → `0012` → `0013` → `0014`. `0008` добавляет email verification;
`0009` — GitHub connection tables; `0010`–`0013` — source types, queue maintenance,
activity events и import batches; `0014` — optimistic versioned editing и точную
import provenance. Readiness требует точную `0014`. Некоторые downgrade intentionally запрещены и
требуют reviewed restore plan.
