# Архитектура бэкенда

Структура модулей адаптирована из `nikepf/startup_insight` на коммите
`45057fbd9b5ef427a79659c63a0b06aa57a5c41a`. В исходнике модули были пустыми,
поэтому здесь сохранено разделение ответственности и добавлена рабочая основа.

| Слой | Ответственность |
| --- | --- |
| `api` | HTTP-маршруты и схемы входных/выходных данных |
| `models` | Подключение к PostgreSQL и модели хранения |
| `services` | Сохранение Notes, auth, orchestration analysis jobs и чтение Flares |
| `ai_engine` | TextAnalyzer и FlareDetector, типы, валидация и Groq adapters |
| `workers` | Последовательное выполнение durable extraction и Flare generation |

Направление зависимостей: HTTP и workers вызывают services; services используют
models, storage и AI-интерфейсы. Реализации конкретных AI- и storage-провайдеров
не должны проникать в API или доменные модели.

Block 4 добавляет отдельную `flare_generation_runs`: completed TextAnalysis и
pinned evidence родительского job → FlareDetector → атомарные записи в
`insights`/`insight_sources` → read-only `/flares`. Обе стадии освобождают DB
connection до вызова провайдера. API не вызывает модель; сохранение Note не
ставит job. Выбор контекста и Analyze относятся к Block 5 и ещё не реализованы.
Подробности: [Flare generation](flare-generation.md).
