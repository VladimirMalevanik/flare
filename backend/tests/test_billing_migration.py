"""Fast migration contract checks; real role/RLS tests live separately."""

import pytest

from test_yandex_migrations import FakeOp, load_migration


@pytest.mark.parametrize("provider,owner", [("self-managed", "flare_billing_executor"), ("yandex", "flare_owner")])
def test_billing_migration_limits_grants_and_supports_managed_owner(monkeypatch, provider, owner):
    migration = load_migration("0021_paddle_billing.py")
    operation = FakeOp()
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", provider)
    migration.upgrade()
    sql = "\n".join(operation.statements)
    assert migration.revision == "0021" and migration.down_revision == "0020"
    for table in migration.TABLES:
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in sql
        assert f"REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker" in sql
    assert "GRANT SELECT(workspace_id) ON public.billing_checkout_intents TO flare_app" in sql
    assert "GRANT SELECT ON public.billing_subscriptions TO flare_app" in sql
    assert "GRANT SELECT ON public.billing_webhook_events TO flare_app" not in sql
    for signature, role in migration.FUNCTIONS.items():
        assert f"ALTER FUNCTION public.{signature} OWNER TO {owner}" in sql
        assert f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,flare_app,flare_worker" in sql
        if role:
            assert f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}" in sql
        else:
            assert f"GRANT EXECUTE ON FUNCTION public.{signature} TO flare_app" not in sql
        assert f"ALTER FUNCTION public.{signature} SET statement_timeout='2s'" in sql
    if provider == "yandex":
        assert "CREATE ROLE flare_billing_executor" not in sql
    else:
        assert "NOLOGIN NOSUPERUSER NOCREATEDB" in sql
        assert "NOCREATEROLE NOINHERIT NOBYPASSRLS" in sql
        assert "GRANT CREATE ON SCHEMA public TO flare_billing_executor" in sql
        assert "REVOKE CREATE ON SCHEMA public FROM flare_billing_executor" in sql
    with pytest.raises(RuntimeError, match="reviewed restore"):
        migration.downgrade()
