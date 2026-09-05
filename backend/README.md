# Flare backend

FastAPI-бэкенд и PostgreSQL-схема Flare. Сейчас реализованы health/readiness
маршруты, миграции, tenant isolation через RLS и модель версионированных
источников. CRUD, авторизация, ingestion workers и AI-провайдеры обозначены
архитектурными границами и будут добавляться следующими этапами.

## Локальный запуск без общего Compose

Из каталога `backend/`:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

Переменные подключения описаны в корневом `.env.example`. Проект БД находится
в [docs/database.md](docs/database.md), а границы слоёв — в
[docs/architecture.md](docs/architecture.md).
