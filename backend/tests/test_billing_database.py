"""Real PostgreSQL billing binding, privilege and atomic replay regressions.

Fixtures require disposable admin/runtime URLs and never reach Paddle or a cloud.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
from uuid import uuid4

import psycopg
from psycopg.errors import InsufficientPrivilege
from psycopg.types.json import Jsonb
import pytest

from app.models.billing import BillingRepository
from app.models.database import Database, WorkspaceIdentity, WritePermissionRequiredError, _connection_is_ready, database_is_ready


pytestmark = pytest.mark.integration
PRICE = "pri_01m3y1nvmgw2avt60bz87161c2"


@pytest.fixture
def billing():
    admin = os.getenv("TEST_DATABASE_URL")
    runtime = os.getenv("DATABASE_URL")
    if not admin or not runtime:
        pytest.skip("Requires disposable migrated PostgreSQL admin/runtime URLs")
    identities = [WorkspaceIdentity(uuid4(), f"auth:{uuid4()}") for _ in range(2)]
    events = []
    with psycopg.connect(admin) as connection:
        for identity in identities:
            connection.execute("INSERT INTO public.workspaces(id,name) VALUES(%s,'Billing fixture')", (identity.workspace_id,))
            connection.execute("""INSERT INTO public.auth_users(id,email,password_hash,name,initial_workspace_id,email_verified_at)
                VALUES(%s,%s,'not-a-login-hash','Billing fixture',%s,clock_timestamp())""",
                (identity.user_id, f"{uuid4()}@billing.invalid", identity.workspace_id))
            connection.execute("INSERT INTO public.workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'owner')",
                (identity.workspace_id, identity.user_id))
    database = Database(runtime, min_size=1, max_size=10)
    database.open()
    repository = BillingRepository(database)

    class Fixture:
        def __init__(self):
            self.database, self.repo, self.identities = database, repository, identities
            self.admin, self.runtime = admin, runtime

        def query(self, query, params=()):
            with psycopg.connect(admin) as connection:
                cursor = connection.execute(query, params)
                return cursor.fetchall() if cursor.description else []

        def intent(self, identity=None):
            digest = sha256(uuid4().bytes).hexdigest()
            expiry = repository.create_intent(identity or identities[0], digest, PRICE, 7200)
            return digest, expiry

        def event(self, digest=None, **overrides):
            now = datetime.now(timezone.utc)
            event = dict(event_id=f"evt_{uuid4().hex}", event_type="subscription.created", occurred_at=now,
                payload_hash=sha256(uuid4().bytes).hexdigest(), subscription_id=f"sub_{uuid4().hex}",
                customer_id=f"ctm_{uuid4().hex}", status="trialing", price_id=PRICE,
                product_id=f"pro_{uuid4().hex}", quantity=1, trial_starts_at=now, trial_ends_at=now+timedelta(days=30),
                current_period_starts_at=None, current_period_ends_at=None, next_billed_at=now+timedelta(days=30),
                scheduled_action=None, scheduled_effective_at=None, intent_hash=digest)
            event.update(overrides)
            events.append(event["event_id"])
            return event

        def next(self, previous, **overrides):
            return self.event(**{**previous, "event_id": f"evt_{uuid4().hex}", "payload_hash": sha256(uuid4().bytes).hexdigest(),
                "event_type": "subscription.updated", "occurred_at": previous["occurred_at"]+timedelta(seconds=1),
                "intent_hash": None, **overrides})

    try:
        yield Fixture()
    finally:
        database.close()
        with psycopg.connect(admin) as connection:
            connection.execute("DELETE FROM public.billing_webhook_events WHERE event_id=ANY(%s)", (events,))
            connection.execute("DELETE FROM public.auth_users WHERE id=ANY(%s)", ([x.user_id for x in identities],))
            connection.execute("DELETE FROM public.workspace_members WHERE workspace_id=ANY(%s)", ([x.workspace_id for x in identities],))
            connection.execute("DELETE FROM public.workspaces WHERE id=ANY(%s)", ([x.workspace_id for x in identities],))


def test_atomic_created_binding_persists_and_ignores_client_identity(billing):
    digest, _ = billing.intent()
    event = billing.event(digest, userId=billing.identities[1].user_id, workspaceId=str(billing.identities[1].workspace_id))
    assert billing.repo.apply_event(event) == "applied"
    rows = billing.repo.subscriptions(billing.identities[0])
    assert len(rows) == 1 and rows[0]["status"] == "trialing"
    assert rows[0]["environment"] == "sandbox" and rows[0]["price_id"] == PRICE
    assert rows[0]["occurred_at"] == event["occurred_at"]
    assert billing.repo.subscriptions(billing.identities[1]) == []
    stored = billing.query("SELECT snapshot FROM public.billing_webhook_events WHERE event_id=%s", (event["event_id"],))[0][0]
    assert "userId" not in stored and "workspaceId" not in stored
    assert billing.query("SELECT consumed_at IS NOT NULL FROM public.billing_checkout_intents WHERE token_hash=%s", (digest,)) == [(True,)]


def test_event_id_replay_is_idempotent_and_changed_body_conflicts(billing):
    digest, _ = billing.intent()
    event = billing.event(digest)
    assert billing.repo.apply_event(event) == "applied"
    assert billing.repo.apply_event(event) == "duplicate"
    assert billing.repo.apply_event({**event, "payload_hash": "f"*64, "status": "canceled"}) == "conflict"
    assert billing.repo.subscriptions(billing.identities[0])[0]["status"] == "trialing"


def test_concurrent_duplicate_deliveries_apply_once(billing):
    digest, _ = billing.intent()
    event = billing.event(digest)
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: billing.repo.apply_event(event), range(12)))
    assert results.count("applied") == 1 and results.count("duplicate") == 11
    assert len(billing.repo.subscriptions(billing.identities[0])) == 1


def test_two_subscriptions_cannot_concurrently_consume_one_intent(billing):
    digest, _ = billing.intent()
    events = [billing.event(digest) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(billing.repo.apply_event, events))
    assert sorted(outcomes) == ["applied", "unlinked"]
    assert len(billing.repo.subscriptions(billing.identities[0])) == 1


def test_consumed_intent_cannot_bind_another_subscription_or_workspace(billing):
    digest, _ = billing.intent()
    event = billing.event(digest)
    assert billing.repo.apply_event(event) == "applied"
    assert billing.repo.apply_event(billing.event(digest)) == "unlinked"
    other_digest, _ = billing.intent(billing.identities[1])
    assert billing.repo.apply_event(billing.next(event, intent_hash=other_digest)) == "applied"
    assert billing.repo.subscriptions(billing.identities[1]) == []
    assert billing.query("SELECT consumed_at FROM public.billing_checkout_intents WHERE token_hash=%s", (other_digest,)) == [(None,)]


@pytest.mark.parametrize("kind", ["unknown", "expired", "late_delivery", "wrong_price", "wrong_quantity"])
def test_initial_binding_fails_closed(billing, kind):
    digest, _ = billing.intent()
    event = billing.event(digest)
    if kind == "unknown":
        event["intent_hash"] = "a"*64
    elif kind in ("expired", "late_delivery"):
        billing.query("UPDATE public.billing_checkout_intents SET created_at=clock_timestamp()-interval '2 hours',expires_at=clock_timestamp()-interval '30 minutes' WHERE token_hash=%s", (digest,))
        if kind == "late_delivery":
            event["occurred_at"] -= timedelta(hours=1)
    elif kind == "wrong_price":
        event["price_id"] = "pri_"+"x"*26
    else:
        event["quantity"] = 0
    assert billing.repo.apply_event(event) == "unlinked"
    assert billing.repo.subscriptions(billing.identities[0]) == []


def test_event_time_allows_short_delivery_delay_after_intent_expiry(billing):
    digest, _ = billing.intent()
    billing.query("UPDATE public.billing_checkout_intents SET created_at=clock_timestamp()-interval '1 hour',expires_at=clock_timestamp()-interval '5 minutes' WHERE token_hash=%s", (digest,))
    event = billing.event(digest, occurred_at=datetime.now(timezone.utc)-timedelta(minutes=6))
    assert billing.repo.apply_event(event) == "applied"


def test_older_event_never_restores_pro_after_cancellation(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    assert billing.repo.apply_event(created) == "applied"
    canceled = billing.next(created, status="canceled", event_type="subscription.canceled")
    assert billing.repo.apply_event(canceled) == "applied"
    old = billing.next(created, occurred_at=created["occurred_at"], status="trialing")
    assert billing.repo.apply_event(old) == "stale"
    assert billing.repo.subscriptions(billing.identities[0])[0]["status"] == "canceled"


def test_updated_before_created_replays_newest_pending_snapshot(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    canceled = billing.next(created, event_type="subscription.canceled", status="canceled")
    assert billing.repo.apply_event(canceled) == "unlinked"
    assert billing.repo.apply_event(created) == "applied"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["status"] == "canceled" and row["occurred_at"] == canceled["occurred_at"]


def test_conflicting_newest_pending_states_fail_closed_at_initial_binding(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    first = billing.next(created, status="active")
    second = billing.next(created, status="canceled")
    assert billing.repo.apply_event(first) == "unlinked"
    assert billing.repo.apply_event(second) == "unlinked"
    assert billing.repo.apply_event(created) == "conflict"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["status"] == "unknown" and row["watermark_conflict"] is True


def test_disabled_owner_or_removed_membership_cannot_bind_a_pending_intent(billing):
    digest, _ = billing.intent()
    identity = billing.identities[0]
    billing.query("UPDATE public.auth_users SET disabled=true WHERE id=%s", (identity.user_id,))
    assert billing.repo.apply_event(billing.event(digest)) == "unlinked"
    billing.query("UPDATE public.auth_users SET disabled=false WHERE id=%s", (identity.user_id,))
    billing.query("DELETE FROM public.workspace_members WHERE workspace_id=%s AND user_id=%s", (identity.workspace_id,identity.user_id))
    assert billing.repo.apply_event(billing.event(digest)) == "unlinked"


def test_equal_timestamp_same_state_is_safe_and_conflicting_state_fails_closed(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    assert billing.repo.apply_event(created) == "applied"
    equivalent = billing.next(created, occurred_at=created["occurred_at"])
    assert billing.repo.apply_event(equivalent) == "stale"
    conflicting = billing.next(created, occurred_at=created["occurred_at"], status="canceled")
    assert billing.repo.apply_event(conflicting) == "conflict"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["status"] == "unknown" and row["watermark_conflict"] is True
    assert billing.repo.apply_event(billing.next(created, occurred_at=created["occurred_at"])) == "conflict"
    assert billing.repo.apply_event(billing.next(created, status="active")) == "applied"
    assert billing.repo.subscriptions(billing.identities[0])[0]["watermark_conflict"] is False


def test_newer_unsupported_price_quantity_or_status_remain_fail_closed(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    assert billing.repo.apply_event(created) == "applied"
    changed = billing.next(created, price_id="pri_"+"y"*26, quantity=0, status="unknown")
    assert billing.repo.apply_event(changed) == "applied"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["bound_price_id"] == PRICE and row["price_id"] == changed["price_id"]
    assert row["quantity"] == 0 and row["status"] == "unknown"


def test_bound_customer_cannot_be_replaced(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    assert billing.repo.apply_event(created) == "applied"
    assert billing.repo.apply_event(billing.next(created, customer_id=f"ctm_{uuid4().hex}")) == "conflict"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["customer_id"] == created["customer_id"]
    assert row["status"] == "unknown" and row["watermark_conflict"] is True


def test_older_customer_transfer_does_not_revoke_a_newer_known_binding(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    assert billing.repo.apply_event(created) == "applied"
    active = billing.next(created, status="active")
    assert billing.repo.apply_event(active) == "applied"
    old_transfer = billing.next(created, occurred_at=created["occurred_at"],customer_id=f"ctm_{uuid4().hex}",status="canceled")
    assert billing.repo.apply_event(old_transfer) == "stale"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["status"] == "active" and row["watermark_conflict"] is False


def test_pending_customer_transfer_cannot_restore_pro_when_created_arrives_late(billing):
    digest, _ = billing.intent()
    created = billing.event(digest)
    transferred = billing.next(created, customer_id=f"ctm_{uuid4().hex}",status="canceled")
    assert billing.repo.apply_event(transferred) == "unlinked"
    assert billing.repo.apply_event(created) == "conflict"
    row = billing.repo.subscriptions(billing.identities[0])[0]
    assert row["status"] == "unknown" and row["customer_id"] == created["customer_id"]


def test_outer_rollback_restores_intent_ledger_and_subscription_together(billing):
    digest, _ = billing.intent()
    event = billing.event(digest)
    encoded = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in event.items()}
    with pytest.raises(RuntimeError), psycopg.connect(billing.runtime) as connection:
        assert connection.execute("SELECT public.apply_paddle_billing_event(%s)", (Jsonb(encoded),)).fetchone() == ("applied",)
        raise RuntimeError("simulate failed transaction")
    assert billing.repo.subscriptions(billing.identities[0]) == []
    assert billing.query("SELECT count(*) FROM public.billing_webhook_events WHERE event_id=%s", (event["event_id"],)) == [(0,)]
    assert billing.repo.apply_event(event) == "applied"


def test_owner_only_intent_even_if_service_write_check_accepts_editor(billing):
    identity = billing.identities[0]
    for role in ("editor", "viewer"):
        billing.query("UPDATE public.workspace_members SET role=%s WHERE workspace_id=%s AND user_id=%s", (role, identity.workspace_id, identity.user_id))
        with pytest.raises(WritePermissionRequiredError):
            billing.intent(identity)


def test_workspace_viewer_reads_shared_subscription_but_cannot_buy_for_the_workspace(billing):
    digest, _ = billing.intent()
    assert billing.repo.apply_event(billing.event(digest)) == "applied"
    owner, other = billing.identities
    billing.query("INSERT INTO public.workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'viewer')", (owner.workspace_id,other.user_id))
    viewer = WorkspaceIdentity(owner.workspace_id, other.user_id)
    assert len(billing.repo.subscriptions(viewer)) == 1
    with pytest.raises(WritePermissionRequiredError):
        billing.intent(viewer)


def test_restrictive_billing_rls_survives_a_future_overbroad_permissive_policy(billing):
    digest, _ = billing.intent()
    assert billing.repo.apply_event(billing.event(digest)) == "applied"
    with psycopg.connect(billing.admin) as connection:
        try:
            for table in ("billing_checkout_intents", "billing_subscriptions"):
                connection.execute(f"CREATE POLICY billing_test_overbroad ON public.{table} FOR SELECT TO flare_app USING(true)")
            connection.execute("SET LOCAL ROLE flare_app")
            assert connection.execute("SELECT count(*) FROM public.billing_subscriptions").fetchone() == (0,)
            assert connection.execute("SELECT count(workspace_id) FROM public.billing_checkout_intents").fetchone() == (0,)
            connection.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",
                (str(billing.identities[1].workspace_id),billing.identities[1].user_id))
            assert connection.execute("SELECT count(*) FROM public.billing_subscriptions").fetchone() == (0,)
        finally:
            connection.rollback()


def test_runtime_privileges_fail_closed_and_readiness_checks_current_schema(billing):
    assert database_is_ready(billing.runtime) is True
    with psycopg.connect(billing.runtime) as connection:
        assert connection.execute("SELECT count(*) FROM public.billing_subscriptions").fetchone() == (0,)
        with pytest.raises(InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT token_hash FROM public.billing_checkout_intents")
        with pytest.raises(InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT * FROM public.billing_webhook_events")
        with pytest.raises(InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT public._apply_paddle_billing_event('{}'::jsonb)")
        with pytest.raises(InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT public.create_billing_checkout_intent(%s,%s,60)", ("a"*64, PRICE))
        for statement in ("UPDATE public.billing_subscriptions SET status='active'", "DELETE FROM public.billing_subscriptions",
            "INSERT INTO public.billing_webhook_events(event_id) VALUES('evt_blocked')"):
            with pytest.raises(InsufficientPrivilege), connection.transaction():
                connection.execute(statement)
    owner = "flare_owner" if os.getenv("FLARE_DATABASE_PROVIDER") == "yandex" else "flare_billing_executor"
    functions = billing.query("""SELECT p.prosecdef,pg_get_userbyid(p.proowner),p.proconfig
        FROM pg_proc p WHERE p.oid IN ('public.create_billing_checkout_intent(text,text,integer)'::regprocedure,
        'public.apply_paddle_billing_event(jsonb)'::regprocedure)""")
    assert len(functions) == 2 and all(row[0] and row[1] == owner for row in functions)
    assert all("search_path=pg_catalog, public, pg_temp" in row[2] and "statement_timeout=2s" in row[2] for row in functions)
    for function in ("public.create_billing_checkout_intent(text,text,integer)", "public.apply_paddle_billing_event(jsonb)"):
        assert billing.query("SELECT has_function_privilege('flare_worker',%s,'EXECUTE')", (function,)) == [(False,)]
        assert billing.query("SELECT has_function_privilege('public',%s,'EXECUTE')", (function,)) == [(False,)]
    if owner == "flare_billing_executor":
        assert billing.query("SELECT rolcanlogin,rolsuper,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=%s", (owner,)) == [(False,False,False,False)]
        assert billing.query("SELECT count(*) FROM pg_auth_members WHERE member=%s::regrole OR roleid=%s::regrole", (owner,owner)) == [(0,)]


def test_capability_restores_context_and_ignores_temp_table_shadowing(billing):
    digest, _ = billing.intent()
    event = billing.event(digest)
    encoded = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in event.items()}
    with psycopg.connect(billing.runtime) as connection:
        connection.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",
            (str(billing.identities[1].workspace_id), billing.identities[1].user_id))
        connection.execute("CREATE TEMP TABLE billing_subscriptions(subscription_id text)")
        assert connection.execute("SELECT public.apply_paddle_billing_event(%s)", (Jsonb(encoded),)).fetchone() == ("applied",)
        assert connection.execute("SELECT current_setting('app.workspace_id'),current_setting('app.user_id')").fetchone() == (
            str(billing.identities[1].workspace_id), billing.identities[1].user_id)
        assert connection.execute("SELECT count(*) FROM public.billing_subscriptions").fetchone() == (0,)


def test_failed_capability_call_restores_caller_context_at_savepoint(billing):
    identity = billing.identities[1]
    with psycopg.connect(billing.runtime) as connection:
        connection.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",
            (str(identity.workspace_id),identity.user_id))
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute("SELECT public.apply_paddle_billing_event('{}'::jsonb)")
        assert connection.execute("SELECT current_setting('app.workspace_id'),current_setting('app.user_id')").fetchone() == (
            str(identity.workspace_id),identity.user_id)


@pytest.mark.parametrize("grant", [
    "GRANT SELECT ON public.billing_webhook_events TO flare_app",
    "GRANT EXECUTE ON FUNCTION public._apply_paddle_billing_event(jsonb) TO flare_app",
])
def test_readiness_rejects_billing_privilege_expansion(billing, grant):
    with psycopg.connect(billing.admin) as connection:
        try:
            connection.execute(grant)
            connection.execute("SET LOCAL ROLE flare_app")
            assert _connection_is_ready(connection) is False
        finally:
            connection.rollback()
