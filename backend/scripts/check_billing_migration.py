"""Read-only post-migration capability check against disposable CI PostgreSQL."""

import os

import psycopg

from app.models.database import CURRENT_SCHEMA_REVISION, database_is_ready


def main():
    assert database_is_ready(os.environ["DATABASE_URL"])
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        assert connection.execute("SELECT version_num FROM public.alembic_version").fetchone() == (CURRENT_SCHEMA_REVISION,)
        for role in ("flare_app", "flare_worker"):
            assert connection.execute("SELECT has_table_privilege(%s,'public.billing_webhook_events','SELECT,INSERT,UPDATE,DELETE')", (role,)).fetchone() == (False,)
            assert connection.execute("SELECT has_table_privilege(%s,'public.billing_subscriptions','INSERT,UPDATE,DELETE')", (role,)).fetchone() == (False,)
        for signature in ("public.create_billing_checkout_intent(text,text,integer)", "public.apply_paddle_billing_event(jsonb)"):
            assert connection.execute("SELECT has_function_privilege('flare_app',%s,'EXECUTE'),has_function_privilege('flare_worker',%s,'EXECUTE')", (signature,signature)).fetchone() == (True,False)
    print(f"PASS: head {CURRENT_SCHEMA_REVISION}; runtime readiness and restricted billing capabilities")


if __name__ == "__main__":
    main()
