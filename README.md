# Flare

Flare — база знаний для стартапов: команда собирает заметки, ссылки, файлы и
аудио, а ИИ находит связи и формирует проверяемые инсайты со ссылками на
конкретные источники.

Это единый монорепозиторий продукта:

```text
frontend/     Next.js-интерфейс
backend/      FastAPI, PostgreSQL, pgvector, миграции и тесты
compose.yaml  локальный запуск всего стека
```

## Что объединено

- Интерфейс импортирован из `fedocc/flare-frontend` на коммите
  `dd2e65b75ac8ab916db03e8986ce490b0a4d3384`.
- Структура бэкенда адаптирована из пустого архитектурного каркаса
  `nikepf/startup_insight` на коммите
  `45057fbd9b5ef427a79659c63a0b06aa57a5c41a`.
- Рабочая SQL-схема, RLS, миграции, тесты и FastAPI-основа перенесены из
  первоначального Flare backend.

Подробности происхождения файлов перечислены в [THIRD_PARTY.md](THIRD_PARTY.md).

## Архитектура

```mermaid
flowchart LR
    UI[Next.js frontend] --> API[FastAPI / api]
    API --> S[services]
    W[workers] --> S
    S --> DB[(PostgreSQL + pgvector)]
    S --> AI[ai_engine interfaces]
    S --> O[(Private object storage)]
```

Backend разделён на `api`, `services`, `models`, `ai_engine` и `workers`.
PostgreSQL хранит команды, документы, версии, текстовые chunks, embeddings,
инсайты и citations. Оригинальные файлы будут храниться отдельно в приватном
object storage.

Готовые версии документов неизменяемы: после обновления старый инсайт продолжает
ссылаться на тот снимок текста, по которому он был создан. Все пользовательские
таблицы изолированы по `workspace_id` с помощью составных внешних ключей и RLS.

## Запуск всего проекта

Нужен Docker Compose:

```sh
cp .env.example .env
docker compose up --build
```

После запуска:

- frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- backend health: http://localhost:8000/health
- database readiness: http://localhost:8000/ready

В текущем этапе frontend использует mock provider и работает как полное демо
интерфейса. Точка подключения настоящего API уже выделена в
`frontend/src/lib/data/api-provider.ts`. Реальные CRUD-маршруты, авторизация,
загрузка бинарных файлов, workers и AI-провайдеры — следующий этап интеграции.

## Проверки

```sh
python -m pip install -e 'backend[dev]'
pytest -q backend/tests
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run build
```

GitHub Actions выполняет обе группы проверок. Backend job поднимает настоящий
PostgreSQL 17 с pgvector и дважды применяет миграции, проверяя повторный запуск.

Документация: [проект БД](backend/docs/database.md),
[слои бэкенда](backend/docs/architecture.md),
[контракт frontend](frontend/docs/API_CONTRACT.md).
