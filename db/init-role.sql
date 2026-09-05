-- Run once as the database administrator; psql syntax, not an Alembic migration.
-- Docker reads APP_PASSWORD from .env. Production credentials are managed separately.
\getenv app_password APP_PASSWORD
CREATE ROLE flare_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS
  PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

