"""Sandbox checkout intents, private event ledger and tenant subscription state."""

import os
from pathlib import Path

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

TABLES = ("billing_checkout_intents", "billing_subscriptions", "billing_webhook_events")
FUNCTIONS = {
    "create_billing_checkout_intent(text,text,integer)": "flare_app",
    "apply_paddle_billing_event(jsonb)": "flare_app",
    "_apply_paddle_billing_event(jsonb)": None,
}


def upgrade():
    managed = os.getenv("FLARE_DATABASE_PROVIDER") == "yandex"
    owner = "flare_owner" if managed else "flare_billing_executor"
    if not managed:
        op.execute("""DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='flare_billing_executor') THEN
                CREATE ROLE flare_billing_executor NOLOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='flare_billing_executor'
                AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolbypassrls))
                OR EXISTS(SELECT 1 FROM pg_auth_members
                    WHERE member='flare_billing_executor'::regrole OR roleid='flare_billing_executor'::regrole) THEN
                RAISE EXCEPTION 'Unsafe billing executor role';
            END IF;
        END $$;""")
    op.execute(Path(__file__).resolve().parents[2].joinpath("db/billing.sql").read_text())
    op.execute(f"GRANT USAGE ON SCHEMA public TO {owner}")
    for table in TABLES:
        op.execute(f"""ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker;
            GRANT SELECT,INSERT,UPDATE ON public.{table} TO {owner};
            CREATE POLICY billing_executor ON public.{table} TO {owner} USING(true) WITH CHECK(true);""")
    # Intent hashes and global event data are never readable through ordinary API SQL.
    op.execute("GRANT SELECT(workspace_id) ON public.billing_checkout_intents TO flare_app")
    op.execute("GRANT SELECT ON public.billing_subscriptions TO flare_app")
    for table in ("billing_checkout_intents", "billing_subscriptions"):
        predicate = f"""workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
            AND EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id={table}.workspace_id
                AND m.user_id=nullif(current_setting('app.user_id',true),''))"""
        op.execute(f"""CREATE POLICY billing_member ON public.{table} FOR SELECT TO flare_app USING({predicate});
            CREATE POLICY billing_member_guard ON public.{table} AS RESTRICTIVE FOR SELECT TO flare_app USING({predicate});""")
    op.execute(f"""GRANT SELECT(id,disabled),UPDATE(disabled) ON public.auth_users TO {owner};
        GRANT SELECT(workspace_id,user_id,role),UPDATE(role) ON public.workspace_members TO {owner};""")
    if not managed:
        op.execute(f"""CREATE POLICY billing_executor_identity ON public.workspace_members AS RESTRICTIVE TO {owner}
            USING(user_id=nullif(current_setting('app.user_id',true),''));
            GRANT CREATE ON SCHEMA public TO {owner};""")
    for signature, role in FUNCTIONS.items():
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {owner}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,flare_app,flare_worker")
        if role:
            op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}")
        op.execute(f"ALTER FUNCTION public.{signature} SET statement_timeout='2s'")
        op.execute(f"ALTER FUNCTION public.{signature} SET lock_timeout='1s'")
    if not managed:
        op.execute(f"REVOKE CREATE ON SCHEMA public FROM {owner}")


def downgrade():
    raise RuntimeError("0021 contains immutable billing/account lineage; use a reviewed restore")
