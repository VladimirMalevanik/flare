"""Daily open counts are anonymous, atomic, UTC-bucketed and owner-scoped."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
import pytest

from app.api import campaign_links as api
from app.api.auth import verified_user
from app.models.campaign_links import CampaignLinkOpener
from app.models.database import Database, WorkspaceIdentity
from app.services.auth_service import AuthenticatedUser
from test_campaign_links import campaign_environment, _create


@pytest.mark.parametrize("managed,owner", [(False, "flare_job_executor"), (True, "flare_owner")])
def test_activity_migration_preserves_restricted_grants_and_function_bounds(monkeypatch, managed, owner):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0026_campaign_link_activity.py"
    spec = importlib.util.spec_from_file_location("campaign_activity_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "yandex" if managed else "self-managed")
    monkeypatch.setattr(module.op, "execute", lambda sql: statements.append(str(sql)))
    module.upgrade()
    sql = "\n".join(statements)
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert f"OWNER TO {owner}" in sql
    assert "SET search_path=pg_catalog,public,pg_temp" in sql
    assert "statement_timeout='250ms'" in sql and "lock_timeout='100ms'" in sql
    assert "ON CONFLICT(link_id,day) DO UPDATE" in sql
    assert "AT TIME ZONE 'UTC'" in sql
    if not managed:
        assert statements[0].startswith("GRANT CREATE ON SCHEMA")
        assert statements[-1].startswith("REVOKE CREATE ON SCHEMA")
    else:
        assert len(statements) == 1


def test_activity_endpoint_requires_the_same_exact_internal_owner_grant():
    user = AuthenticatedUser(f"auth:{uuid4()}", uuid4(), "customer@example.invalid", "Customer", "owner", "Customer", True, True)
    app = FastAPI()
    app.include_router(api.router)
    app.state.database = object()  # Forbidden requests must not reach the database.
    app.state.settings = SimpleNamespace(dev_mode=False, environment="production", developer_mail_accounts=None)
    for denied in (user, replace(user, role="editor"), replace(user, email_verified=False)):
        app.dependency_overrides[verified_user] = lambda: denied
        with TestClient(app) as client:
            response = client.get("/campaign-links/activity")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "campaign_links_forbidden"


@pytest.mark.integration
@pytest.mark.parametrize("days", [7, 30, 90])
def test_empty_activity_has_unknown_coverage_and_a_bounded_daily_range(days):
    with campaign_environment() as environment, environment.client() as client:
        response = client.get("/campaign-links/activity", params={"days": days})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["days"] == days and data["timezone"] == "UTC"
        assert data["recordingStartedAt"] is None
        assert data["totalOpens"] == 0 and data["topLinks"] == []
        assert len(data["daily"]) == days
        assert all(day["opens"] is None for day in data["daily"])
        end = datetime.fromisoformat(data["generatedAt"]).astimezone(timezone.utc).date()
        assert [day["date"] for day in data["daily"]] == [(end - timedelta(days=days - 1 - offset)).isoformat() for offset in range(days)]
        for invalid in (0, 8, 31, 91, 100000, "bad"):
            assert client.get("/campaign-links/activity", params={"days": invalid}).status_code == 422
        assert client.get("/campaign-links/activity", params={"linkId": "invalid"}).status_code == 422


@pytest.mark.integration
def test_real_redirects_increment_daily_and_lifetime_counts_without_cookies_then_archive_stops_both():
    with campaign_environment() as environment, environment.client() as client:
        link = _create(client)
        for _ in range(3):
            response = client.get(f"/campaign-links/r/{link['slug']}", follow_redirects=False)
            assert response.status_code == 302
            assert "set-cookie" not in response.headers
        response = client.get("/campaign-links/activity", params={"days": 7, "linkId": link["id"]})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["totalOpens"] == 3
        assert data["daily"][-1]["opens"] == 3
        assert all(row["opens"] is None for row in data["daily"][:-1])
        assert data["topLinks"][0]["opens"] == 3
        assert client.get(f"/campaign-links/{link['id']}").json()["clickCount"] == 3
        client.post(f"/campaign-links/{link['id']}/archive")
        assert client.get(f"/campaign-links/r/{link['slug']}", follow_redirects=False).status_code == 302
        archived = client.get("/campaign-links/activity").json()
        assert archived["totalOpens"] == 3
        assert archived["topLinks"][0]["archivedAt"] is not None


@pytest.mark.integration
def test_legacy_totals_are_not_backfilled_and_out_of_range_days_do_not_enter_period_totals():
    with campaign_environment() as environment, environment.client() as client:
        link = _create(client)
        today = environment.fetchone_admin("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date", ())[0]
        started = datetime.combine(today - timedelta(days=2), datetime.min.time(), timezone.utc)
        environment.execute_admin("UPDATE public.campaign_links SET click_count=60,activity_started_at=%s WHERE id=%s", (started, UUID(link["id"])))
        for day, opens in [(today - timedelta(days=30), 40), (today - timedelta(days=2), 4), (today, 6)]:
            environment.execute_admin("INSERT INTO public.campaign_link_daily_opens(link_id,day,opens) VALUES(%s,%s,%s)", (UUID(link["id"]), day, opens))
        data = client.get("/campaign-links/activity", params={"days": 7}).json()
        assert data["totalOpens"] == 10
        assert [row["opens"] for row in data["daily"]] == [None, None, None, None, 4, 0, 6]
        assert data["topLinks"][0]["opens"] == 10
        assert client.get(f"/campaign-links/{link['id']}").json()["clickCount"] == 60


@pytest.mark.integration
def test_link_filter_and_rls_cannot_read_another_workspace_or_write_daily_rows():
    with campaign_environment() as environment:
        workspace, user = uuid4(), f"activity-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=user) as client:
            first, second = _create(client, label="First"), _create(client, label="Second")
            client.get(f"/campaign-links/r/{first['slug']}", follow_redirects=False)
            for _ in range(2):
                client.get(f"/campaign-links/r/{second['slug']}", follow_redirects=False)
            all_data = client.get("/campaign-links/activity").json()
            assert all_data["totalOpens"] == 3
            assert [row["opens"] for row in all_data["topLinks"]] == [2, 1]
            selected = client.get("/campaign-links/activity", params={"linkId": first["id"]}).json()
            assert selected["totalOpens"] == 1
            assert [row["id"] for row in selected["topLinks"]] == [first["id"]]
        with environment.client() as other:
            assert other.get("/campaign-links/activity").json()["totalOpens"] == 0
            assert other.get("/campaign-links/activity", params={"linkId": first["id"]}).status_code == 404
        database = Database(environment.runtime_url)
        try:
            with database.workspace_transaction(WorkspaceIdentity(uuid4(), user)) as connection:
                assert connection.execute("SELECT * FROM public.campaign_link_daily_opens").fetchall() == []
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with database.workspace_transaction(WorkspaceIdentity(workspace, user), write=True) as connection:
                    connection.execute("INSERT INTO public.campaign_link_daily_opens(link_id,day,opens) VALUES(%s,current_date,10)", (UUID(first["id"]),))
        finally:
            database.close()


@pytest.mark.integration
def test_counter_function_uses_utc_and_concurrent_opens_remain_exact():
    with campaign_environment() as environment, environment.client() as client:
        link = _create(client)
        def count(_):
            with psycopg.connect(environment.runtime_url) as connection:
                connection.execute("SET LOCAL TIME ZONE 'Pacific/Kiritimati'")
                return connection.execute("SELECT public.campaign_link_count(%s)", (link["slug"],)).fetchone()[0]
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert all(pool.map(count, range(24)))
        data = client.get("/campaign-links/activity").json()
        assert data["daily"][-1]["opens"] == data["totalOpens"] == 24
        assert client.get(f"/campaign-links/{link['id']}").json()["clickCount"] == 24


@pytest.mark.integration
def test_daily_write_failure_rolls_back_both_counters_but_does_not_break_redirect():
    with campaign_environment() as environment, environment.client() as client:
        link = _create(client)
        environment.execute_admin("INSERT INTO public.campaign_link_daily_opens(link_id,day,opens) VALUES(%s,(clock_timestamp() AT TIME ZONE 'UTC')::date,9223372036854775807)", (UUID(link["id"]),))
        response = client.get(f"/campaign-links/r/{link['slug']}", follow_redirects=False)
        assert response.status_code == 302
        assert client.get(f"/campaign-links/{link['id']}").json()["clickCount"] == 0
        assert environment.fetchone_admin("SELECT opens FROM public.campaign_link_daily_opens WHERE link_id=%s", (UUID(link["id"]),))[0] == 9223372036854775807
