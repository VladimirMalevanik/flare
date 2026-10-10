"""Operator tests use only disposable fixture connections and synthetic accounts."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4
import importlib.util

import psycopg
import pytest
_spec = importlib.util.spec_from_file_location("growth_ops", Path(__file__).resolve().parents[1] / "scripts/growth_ops.py")
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)
OperatorError, REVISION = ops.OperatorError, ops.REVISION
configure, maintenance, read_policy, report = ops.configure, ops.maintenance, ops.read_policy, ops.report
utc_time, validate_policy = ops.utc_time, ops.validate_policy
from app.services.attribution_service import AttributionService
from app.services.item_service import ItemService
from test_acquisition import growth, enabled_growth_policy  # noqa: F401

POLICY_PATH = Path(__file__).resolve().parents[2] / "docs/implementation/GROWTH-003/policy.proposed.json"


@pytest.mark.parametrize("change", [
    {"enabled": True}, {"cookie_seconds": 3600}, {"min_cohort": 2}, {"revision": "unknown"},
    {"tokens": {}}, {"network_hour": 1001}, {"global_hour": True}, {"deadline_ms": 501}, {"cleanup_owner": ""},
])
def test_policy_validation_does_not_silently_change_notice(change):
    with pytest.raises(OperatorError):
        validate_policy(read_policy(POLICY_PATH) | change)


def test_duplicate_policy_fields_are_rejected(tmp_path):
    file = tmp_path / "duplicate.json"
    file.write_text('{"revision":"one","revision":"two"}')
    with pytest.raises(OperatorError, match="Duplicate"):
        read_policy(file)


def test_report_times_are_explicit_utc_and_ambiguous_times_rejected():
    assert utc_time("2026-10-10T10:00:00+03:00").hour == 7
    with pytest.raises(OperatorError):
        utc_time("2026-10-10T10:00:00")


def activate_synthetic(environment):
    with psycopg.connect(environment.admin_url, autocommit=True) as connection:
        connection.execute("UPDATE public.growth_policy SET enabled=false")
        # This is an isolated test assertion, never an approval of production.
        return configure(connection, read_policy(POLICY_PATH), expected_revision="nonproduction-v1", approved_by="Vova", cleanup_ready=True)


def test_activation_requires_approval_cleanup_and_unchanged_disabled_policy(growth):
    _, environment, _, _ = growth
    with psycopg.connect(environment.admin_url, autocommit=True) as connection:
        for approved, ready in (("Fedor", True), ("Vova", False)):
            with pytest.raises(OperatorError):
                configure(connection, read_policy(POLICY_PATH), expected_revision="nonproduction-v1", approved_by=approved, cleanup_ready=ready)
        with pytest.raises(OperatorError):
            configure(connection, read_policy(POLICY_PATH), expected_revision="nonproduction-v1", approved_by="Vova", cleanup_ready=True)
        assert connection.execute("SELECT revision,enabled FROM public.growth_policy").fetchone() == ("nonproduction-v1", True)
    assert activate_synthetic(environment)["revision"] == REVISION


def test_three_x_refs_link_to_signup_and_committed_capture_without_identity_export(growth):
    db, environment, _, account = growth
    activate_synthetic(environment)
    since = datetime.now(timezone.utc)
    users = []
    for label in ("ilyas", "fedor", "flare"):
        for _ in range(5):
            reference = AttributionService(db).touch(reference=None, peer="synthetic-" + uuid4().hex,
                revision=REVISION, touch={"landing_route": "/", "utm_source": "x", "utm_medium": "organic_social",
                "utm_campaign": "launch_2026_10", "utm_content": label, "ref": label, "referrer_domain": "t.co"})
            assert reference
            user, _ = account(reference); users.append(user)
            ItemService(db, user.identity).create_note(title="Synthetic", content="Synthetic private content excluded from report")
    with psycopg.connect(os.environ["WORKER_DATABASE_URL"], autocommit=True) as connection:
        reconciled = maintenance(connection, "reconcile", batch=5, max_batches=10)
        assert reconciled["complete"]
    # Provision only inside a rollback transaction if CI has no reporting role.
    # No production credentials or persistent test access are created.
    with psycopg.connect(environment.admin_url) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='flare_growth_reporter'").fetchone():
            connection.execute("CREATE ROLE flare_growth_reporter NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION")
        connection.execute("GRANT USAGE ON SCHEMA public TO flare_growth_reporter")
        connection.execute("GRANT EXECUTE ON FUNCTION public.growth_report(timestamptz,timestamptz,text,text) TO flare_growth_reporter")
        connection.execute("SET LOCAL ROLE flare_growth_reporter")
        value = report(connection, since, datetime.now(timezone.utc))
        connection.rollback()
    assert value["metrics"]["accounts"] == 15
    assert value["metrics"]["committed_outcome"] == 15
    assert {bucket["ref"] for bucket in value["attribution"]} == {"ilyas", "fedor", "flare"}
    assert all(bucket["metrics"]["accounts"] == 5 for bucket in value["attribution"])
    serialized = json.dumps(value)
    assert "Synthetic private content" not in serialized
    assert all(user.user_id not in serialized and str(user.workspace_id) not in serialized for user in users)


def test_incomplete_maintenance_cannot_claim_exhaustion():
    class Row:
        def fetchone(self): return (1,)
    class Connection:
        def execute(self, *_): return Row()
        def transaction(self):
            from contextlib import nullcontext
            return nullcontext()
    from unittest.mock import patch
    with patch.object(ops, "restricted_role"):
        with pytest.raises(OperatorError, match="budget exhausted"):
            maintenance(Connection(), "reconcile", batch=1, max_batches=2)
