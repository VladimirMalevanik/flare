# Архитектура бэкенда

Структура модулей адаптирована из `nikepf/startup_insight` на коммите
`45057fbd9b5ef427a79659c63a0b06aa57a5c41a`. В исходнике модули были пустыми,
поэтому здесь сохранено разделение ответственности и добавлена рабочая основа.

| Слой | Ответственность |
| --- | --- |
| `api` | HTTP-маршруты и схемы входных/выходных данных |
| `models` | Подключение к PostgreSQL и модели хранения |
| `services` | Сохранение источников и импортов, auth, analytics, queue operations, orchestration analysis jobs и чтение Flares |
| `ai_engine` | TextAnalyzer и FlareDetector, типы, валидация и Groq adapters |
| `workers` | Последовательное выполнение durable extraction и Flare generation |

Направление зависимостей: HTTP и workers вызывают services; services используют
models, storage и AI-интерфейсы. Реализации конкретных AI- и storage-провайдеров
не должны проникать в API или доменные модели.

`flare_generation_runs` добавляет отдельную стадию: completed TextAnalysis и
pinned evidence родительского job → FlareDetector → атомарные записи в
`insights`/`insight_sources` → read-only `/flares`. Обе стадии освобождают DB
connection до вызова провайдера. API не вызывает модель синхронно: сохранение
любого поддерживаемого входного типа через `/items` и текстовый импорт через
`/imports` запускают durable очередь. Явный `/analyze` создаёт отдельный
ограниченный прогон с серверным выбором контекста. Подробности:
[Analyze](analyze.md) и [Flare generation](flare-generation.md).

GitHub App integration находится в тех же границах: `api/github.py` вызывает
`GitHubConnectionService`, provider-клиент находится в `integrations/github.py`,
а workspace-scoped state и connection metadata сохраняются через models. Это
connection flow без commits/PR/issues ingestion.
