import os

from alembic import context
from app.environment import load_project_dotenv
from sqlalchemy import create_engine, pool

load_project_dotenv(allowed_roles={"migration"})
url = os.environ["MIGRATION_DATABASE_URL"]
database_provider = os.getenv("FLARE_DATABASE_PROVIDER", "self-managed")
if database_provider not in {"self-managed", "yandex"}:
    raise RuntimeError(
        "FLARE_DATABASE_PROVIDER must be 'self-managed' or 'yandex'"
    )

if context.is_offline_mode():
    if database_provider == "yandex":
        raise RuntimeError(
            "Yandex migrations require an online connection for prerequisite checks"
        )
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
