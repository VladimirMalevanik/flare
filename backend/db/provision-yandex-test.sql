-- CI-only emulation of Yandex Cloud control-plane provisioning.
-- Never run this file against Yandex Managed PostgreSQL: create users and
-- enable pgvector there through the console, CLI or API instead.
\getenv owner_password OWNER_PASSWORD
\getenv app_password APP_PASSWORD
\getenv worker_password WORKER_PASSWORD

CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE flare_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
  PASSWORD :'owner_password';
CREATE ROLE flare_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
  PASSWORD :'app_password';
CREATE ROLE flare_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
  PASSWORD :'worker_password';

SELECT format('ALTER DATABASE %I OWNER TO flare_owner', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
