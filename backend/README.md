# Flare backend

FastAPI-бэкенд и PostgreSQL-схема Flare. Реализованы health/readiness,
миграции, tenant isolation через RLS и первый вертикальный сценарий заметок:

- `POST /items` атомарно создаёт документ, готовую версию и текстовый chunk;
- `GET /items` поддерживает `query`, `type` и `limit`;
- `GET /items/{id}` возвращает одну активную заметку;
- `DELETE /items/{id}` выполняет soft delete, сохраняя версию и chunk.

Ответы используют camelCase-контракт фронтенда. Файлы, URL, аудио, настоящая
авторизация, ingestion workers и AI-провайдеры остаются следующими этапами.

## Локальный запуск без общего Compose

Из каталога `backend/`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

Для локального API заметок нужно явно включить серверную dev-identity:

```sh
export FLARE_DEV_MODE=true
export FLARE_DEV_WORKSPACE_ID=00000000-0000-4000-8000-000000000001
export FLARE_DEV_USER_ID=local-dev-user
export FLARE_DEV_WORKSPACE_NAME='Flare Local'
```

Эти значения не принимаются из HTTP-заголовков. При запуске фиксированные
workspace и owner создаются идемпотентно. В каждой операции сервер снова
проверяет членство и роль после установки transaction-local RLS-контекста.
Без `FLARE_DEV_MODE=true` item-маршруты закрыты до подключения авторизации.

Пример создания заметки:

```sh
curl -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"type":"note","content":"Клиентам нужен поиск с цитатами"}'
```

Переменные подключения описаны в корневом `.env.example`. Проект БД находится
в [docs/database.md](docs/database.md), а границы слоёв — в
[docs/architecture.md](docs/architecture.md).
