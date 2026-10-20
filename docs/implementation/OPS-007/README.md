# OPS-007 — стабильное получение ffprobe в CI

Владелец прямо поручил исправить скачивание ffprobe, перезапустить проверки и после
успешного CI слить исправление импорта PR74. Production deployment не запрошен.

## Причина и проверенный источник

PR74 проходит frontend и PostgreSQL pytest, затем self-managed DB job падает на
TLS handshake к johnvansickle.com. Попытки 1–3 повторили сбой. Ограниченный HTTPS
curl IPv4/HTTP1.1 также получил SSL connection timeout с локального компьютера.

Уточнение прежнего отчёта: в исходном checks.yml native ffprobe/voice-runtime
проверяются **только** на self-managed профиле БД. Успешный Yandex job не доказывал
прохождение этой проверки. Это не self-hosted runner: оба используют ubuntu-latest.

Найден [immutable release publicala/ffmpeg-static v7.0.2](https://github.com/publicala/ffmpeg-static/releases/tag/v7.0.2).
Его archive скачан и проверен по **ранее закреплённым** в Flare значениям:

- archive: 41 888 096 байт,
  SHA512 `e80880362208de7437f0eb98d25ec6676df122a04613a818bb14101c3e1ccf91feab06246d40359b887b147af65d80eef5dba99964cac469bcb560f1a063d737`;
- ffprobe: 79 665 792 байт,
  SHA256 `4f231a1960d83e403d08f7971e271707bec278a9ae18e21b8b5b03186668450d`.

Зеркало используется как источник доступности, а не как новый корень доверия:
версия, member path, архивный SHA512 и бинарный SHA256 не изменены. Иные байты
не принимаются даже при правильном имени файла или валидном TLS.

## Изменение

- Основной HTTPS-источник — фиксированный GitHub release; исходный HTTPS endpoint
  оставлен резервным. Нет произвольного URL из переменных окружения или аргументов.
- До 2 попыток на источник, повторы только при транспортных ошибках. Частично
  скачанный файл удаляется, следующий запрос не дописывает старое содержимое.
  Hash mismatch, превышение размера и нарушение HTTPS вызывают немедленную ошибку.
- Сохраняется стандартная проверка TLS-сертификатов urllib; HTTP/file/FTP redirects
  запрещены. Нет unverified SSL context или отключения сертификатов.
- I/O timeout до 15 с, общий 90-секундный бюджет проверяется перед запросами и между
  чтениями. Один уже начатый сетевой read ограничен socket timeout. В CI весь шаг
  native verification дополнительно ограничен 3 минутами.
- Архив ограничен 64 MiB; извлекается только ожидаемый обычный member до 96 MiB.
  Проверка бинарного digest предшествует атомарной публикации файла.
- Cache сохраняет только публичный закреплённый binary, с OS/architecture и hash
  installer в точном ключе. Prefix restore keys отсутствуют. SHA256 проверяется
  **при каждом запуске**, включая cache hit; испорченный cache скачивается заново,
  symlink отвергается. Секреты, окружение или application data в cache не попадают.
- Использован [actions/cache v6.1.0](https://github.com/actions/cache/releases/tag/v6.1.0),
  закреплённый по commit `55cc8345863c7cc4c66a329aec7e433d2d1c52a9`.
  Совместимость Node 24/minimum runner проверена по официальному README; hosted
  ubuntu-latest не требует настройки чужих runners. Cache опционален и ограничен
  по времени, а следующая проверка exact binary и реальный voice smoke обязательны.
- Native verification перенесена перед миграциями/pytest, чтобы сетевой сбой
  обнаруживался до долгих DB-тестов. Матрица БД, тесты, pip check, права workflow
  contents: read и native проверка на сгенерированном WAV сохраняются.

Python/PIP/NPM production dependencies, версия ffprobe и application/analysis code
не менялись. Скрипт также входит в server bootstrap: после будущего deployment
он получит тот же mirror-first transport с прежним exact binary. Уже работающий
сервер и его файлы этой задачей не изменялись.

## Проверки

Локально 17 installer tests passed: существующие extraction/binary mismatch/cache,
реальная логика download→verify→install с mock transport, approved-source fallback,
partial read retry, bounded exhaustion/cleanup, fail-closed archive mismatch,
лимит размера по заголовку и телу, slow-read deadline, запрет HTTP/file/FTP redirects, HTTPS asset
redirect, corrupted cache и symlink. Тесты не обращаются во внешнюю сеть или БД.

Новый installer отдельно выполнил настоящий HTTPS download из GitHub, проверил
обе суммы и установил файл во временную папку. Повторный вызов использовал проверенный
local cache. Linux executable на macOS не запускался; настоящий voice-runtime smoke
должен пройти на Linux CI. Полная CI-матрица и интеграция PR74 остаются обязательными;
их фактические SHA/ссылки записываются в task-sync и PR после выполнения.

Новые публикации release/assets, платные сервисы, production secrets/deployment,
реальные записи/провайдеры/AI/mail/payment и файлы активной API-005 не затрагивались.
