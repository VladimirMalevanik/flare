# Yandex Managed PostgreSQL для тестового окружения

Этот вариант позволяет запускать frontend, FastAPI и worker на компьютере без
Docker, а PostgreSQL 17 и данные хранить в Yandex Cloud. Для первого теста
достаточно одного хоста. Это не отказоустойчивая конфигурация: при недоступности
единственного хоста приложение временно потеряет доступ к базе.

10 сентября 2026 года предварительный расчёт в консоли для окружения
`PRESTABLE`, одного хоста `b1.medium` (2 vCPU, 4 ГБ RAM) и 10 ГБ
`network-hdd` составлял примерно **3 157,34 ₽ в месяц**. Это ориентир для
выбранной тестовой конфигурации, а не
фиксированная цена. Итоговый расчёт в консоли при создании кластера имеет
приоритет: отдельно могут тарифицироваться вычисления, хранилище, резервные
копии и исходящий трафик. Проверяйте остаток гранта и актуальные
[тарифы Managed PostgreSQL][pricing]. Условия использования гранта описаны на
странице [бонусного счёта][grant]. Стартовый грант из текущего предложения
действует 60 дней: неизрасходованный остаток после этого срока сгорает, поэтому
после теста удалите ненужные ресурсы или заранее перейдите на обычную оплату.

## 1. Создать кластер, базу и пользователей

В Yandex Cloud откройте **Managed Service for PostgreSQL** и настройте кластер:

- PostgreSQL 17;
- окружение `PRESTABLE` для этого одноразового тестового кластера; для стабильного
  развёртывания выбирайте `PRODUCTION` — окружение после создания не меняется;
- один хост и минимальная подходящая конфигурация для теста;
- публичный доступ к хосту;
- security group с входящим TCP-портом `6432` только от текущего публичного IP
  разработчика в формате `x.x.x.x/32`;
- защита кластера от удаления;
- ежедневное окно резервного копирования и срок хранения не меньше семи дней;
- окно point-in-time recovery (PITR), которое определяется сроком хранения
  автоматических резервных копий.

Перед рискованной миграцией создавайте ручную резервную копию. Порядок
восстановления и ограничения PITR описаны в документации по
[резервным копиям][backups].

Не открывайте порт для `0.0.0.0/0`. Если публичный IP изменится, замените правило
в security group. При переносе backend в облако разрешите адрес backend или
используйте приватную сеть.

В секции **Настройки базы данных** формы создания укажите базу `flare` и
первого пользователя `flare_owner`. Этот пользователь будет создан вместе с
кластером и станет владельцем первой базы данных. После готовности кластера на
вкладке **Пользователи** создайте ещё двух пользователей и разрешите им доступ
к базе `flare`. У всех трёх должны быть разные пароли:

| Пользователь | Назначение |
| --- | --- |
| `flare_owner` | владелец базы и запуск миграций |
| `flare_app` | подключение FastAPI во время работы |
| `flare_worker` | выполнение фоновых AI-задач |

Не выдавайте этим пользователям административные роли Managed PostgreSQL.
Приложение проверяет, что `flare_owner` владеет базой, и что все три
пользователя не имеют `SUPERUSER`, `BYPASSRLS`, `CREATEROLE`, `CREATEDB` и
членства в других ролях. Пользователи создаются в панели управления, потому что
Managed PostgreSQL не разрешает приложению самостоятельно создавать кластерные
роли.

Для базы `flare` включите расширение **pgvector** через интерфейс Yandex Cloud.
В зависимости от представления каталога оно может называться `vector` или
`pgvector`. Миграция в режиме `FLARE_DATABASE_PROVIDER=yandex` проверяет
пользователей, владельца и расширение до создания таблиц и не пытается
устанавливать pgvector через SQL.

Инструкции Yandex Cloud: [создание кластера][quickstart],
[управление пользователями][users] и [подключение расширений][extensions].

## 2. Настроить TLS и отдельные окружения

Скачайте корневой сертификат Yandex Cloud один раз:

```sh
mkdir -p ~/.postgresql
curl --create-dirs -o ~/.postgresql/root.crt \
  https://storage.yandexcloud.net/cloud-certs/CA.pem
chmod 0600 ~/.postgresql/root.crt
```

В строках подключения используйте специальный FQDN текущего ведущего хоста:

```text
c-<cluster-id>.rw.mdb.yandexcloud.net
```

Yandex обновляет его при смене primary, но после failover DNS может некоторое
время указывать на прежний хост. Клиент должен повторять временно неудачные
подключения и записи; для текущего однохостового теста failover отсутствует.
Используйте порт `6432`, `sslmode=verify-full`,
`target_session_attrs=read-write` и абсолютный путь к сертификату. Подключение
по IP не подходит для проверки имени сертификата.

Разнесите секреты владельца, API и worker по трём файлам:

```sh
cp .env.yandex.migrate.example .env.yandex.migrate
cp .env.yandex.api.example .env.yandex.api
cp .env.yandex.worker.example .env.yandex.worker
cp frontend/.env.example frontend/.env.local
chmod 0600 .env.yandex.migrate .env.yandex.api .env.yandex.worker
```

Замените значения в угловых скобках. Если пароль содержит `@`, `:`, `/`, `?`,
`#`, `%` или другие специальные символы URL, закодируйте его один раз в
percent-encoding. Рабочие env-файлы исключены из Git. Не отправляйте их в чат и
не добавляйте в коммиты.

`MIGRATION_DATABASE_URL` должен находиться только в `.env.yandex.migrate`.
FastAPI получает только `.env.yandex.api` с ограниченным `DATABASE_URL`, а
worker — только `.env.yandex.worker` с `WORKER_DATABASE_URL`. Frontend не должен
получать ни одну строку подключения к PostgreSQL. Поле `FLARE_PROCESS_ROLE` в
каждом шаблоне не даёт запустить API с миграционным файлом; загрузчик также
удаляет унаследованный `MIGRATION_DATABASE_URL`, если он остался в терминале от
старого `source .env`.

Подробнее о TLS и форматах подключения — в [официальной инструкции][connect].

## 3. Установить зависимости и применить миграции

Из корня репозитория установите backend-зависимости:

```sh
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -e 'backend[dev]'
```

Затем один раз выполните миграции от `flare_owner`, явно указав предназначенный
для них env-файл:

```sh
FLARE_DOTENV_PATH="$PWD/.env.yandex.migrate" \
  backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
```

Не загружайте `.env.yandex.migrate` через `source` перед запуском API или worker.
Не запускайте полный набор интеграционных тестов против общей облачной базы:
часть тестов рассчитана на одноразовый локальный кластер и меняет данные и роли.

## 4. Запустить проект без Docker

В первом терминале из корня репозитория запустите API:

```sh
FLARE_DOTENV_PATH="$PWD/.env.yandex.api" \
  backend/.venv/bin/uvicorn --app-dir backend app.main:app --reload
```

Во втором терминале запустите frontend. Next.js самостоятельно прочитает
`frontend/.env.local`; DB-секреты ему не нужны:

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

Откройте http://localhost:3000. Проверка готовности backend должна отвечать
успешно:

```sh
curl http://127.0.0.1:8000/ready
```

После `ready` выполните полный пользовательский smoke в браузере:
зарегистрируйтесь, подтвердите email, создайте Note, откройте Vault, обновите
страницу и снова откройте Note. Так одновременно проверяются сессия, RLS,
сохранение источника и постановка job в очередь. Статус очереди и агрегированные
счётчики доступны owner через Swagger UI на `http://localhost:8000/docs` в той
же авторизованной browser-сессии.

Команда `curl` выполняется в обычном терминале. Если перед приглашением виден
`flare=#` или `flare-#`, сначала выйдите из `psql` командой `\q`.

Worker запускается отдельно и нужен только для фонового AI-анализа. Перед
запуском укажите действующий `GROQ_API_KEY` в `.env.yandex.worker`:

```sh
FLARE_DOTENV_PATH="$PWD/.env.yandex.worker" \
  backend/.venv/bin/python -m app.workers.analysis_worker --once
```

Без ключа worker завершится с ошибкой ещё при инициализации AI-клиента.

## 5. Проверить реальную облачную базу

Сначала проверьте служебные признаки от `flare_owner`. Команда запросит пароль;
не записывайте его в историю shell:

```sh
psql "host=c-<cluster-id>.rw.mdb.yandexcloud.net port=6432 dbname=flare user=flare_owner sslmode=verify-full sslrootcert=$HOME/.postgresql/root.crt target_session_attrs=read-write"
```

Внутри `psql` выполните только проверки каталога и миграции:

```sql
SELECT current_user, current_database();
SELECT datdba::regrole AS database_owner
FROM pg_database
WHERE datname = current_database();
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pgvector');
SELECT version_num FROM alembic_version;
```

Таблица `documents` защищена `FORCE ROW LEVEL SECURITY`. Запрос от
`flare_owner` без установленного пользовательского контекста не является
корректной проверкой сохранения и может вернуть ноль строк. Данные проверяйте
через пользовательский путь: зарегистрируйтесь в интерфейсе, создайте Note,
откройте Vault, обновите страницу и снова откройте заметку. Так проверяются сразу
API, сессия, RLS и постоянное хранение. Учётную запись `flare_owner` не
используйте как runtime-подключение для обхода этого сценария.

Если соединение не устанавливается, проверьте публичный доступ у хоста, правило
`6432` для текущего `/32`, специальный read-write FQDN, путь к CA и
URL-кодирование пароля.

## 6. Что проверяет CI

Yandex-ветка GitHub Actions запускается на обычном PostgreSQL-контейнере и
эмулирует подготовку ролей и pgvector, которую в облаке выполняет control plane.
Она проверяет условную логику миграций и повторный запуск, но не воспроизводит
запреты и привилегии реального Yandex Managed PostgreSQL.

До merge или релиза обязательно выполните на настоящем тестовом кластере шаги
3–5: миграцию, `/ready`, регистрацию, создание Note и чтение Note после
обновления страницы. Если используется AI worker, отдельно выполните один job.
Только этот smoke подтверждает совместимость с управляемыми ролями, TLS и
сетевыми правилами Yandex Cloud.

## 7. Откат и удаление тестового кластера

До переключения сохраните прежние env-файлы с рабочими DSN и не удаляйте старый
кластер. При проблеме:

1. остановите API и worker;
2. снова запустите их с прежними `FLARE_DOTENV_PATH` и DSN;
3. проверьте `/ready`, вход и чтение существующей Note;
4. оставьте новый кластер для диагностики или восстановите его из резервной
   копии в отдельный кластер.

Не выполняйте downgrade схемы в рабочей базе как первый способ отката. После
проверки возврата можно удалить тестовый кластер: при необходимости сохраните
резервную копию, отключите защиту от удаления и подтвердите удаление в консоли.
Хранение и резервные копии могут продолжать тарифицироваться, пока ресурсы
существуют.

[pricing]: https://yandex.cloud/ru/docs/managed-postgresql/pricing
[grant]: https://yandex.cloud/ru/docs/getting-started/usage-grant
[quickstart]: https://yandex.cloud/ru/docs/managed-postgresql/quickstart
[users]: https://yandex.cloud/ru/docs/managed-postgresql/operations/cluster-users
[extensions]: https://yandex.cloud/ru/docs/managed-postgresql/operations/extensions/cluster-extensions
[connect]: https://yandex.cloud/ru/docs/managed-postgresql/operations/connect
[backups]: https://yandex.cloud/ru/docs/managed-postgresql/concepts/backup
