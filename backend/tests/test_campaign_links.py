"""Campaign-link validation, tenant boundaries and aggregate redirect counts."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import campaign_links as campaign_api
from app.api.auth import verified_user
from app.config import Settings
from app.models import campaign_links as campaign_model
from app.models.campaign_links import (
    CampaignLinkLimitReached,
    CampaignLinkOpener,
    CampaignLinkRepository,
    SLUG_PATTERN,
)
from app.models.database import Database, WorkspaceIdentity, _connection_is_ready
from app.services.campaign_links import (
    InvalidCampaignLink,
    destination_url,
    normalize_label,
    normalize_utm,
    public_origin,
    validate_destination,
)
from app.services.auth_service import AuthenticatedUser
from test_items_api import ApiEnvironment
from test_team import team  # noqa: F401; shared Team project fixture


PAYLOAD = {
    "label": " X launch / founder post ",
    "destinationPath": "/register",
    "utmSource": " X ",
    "utmMedium": " Organic_Social ",
    "utmCampaign": " Launch-2026.10 ",
    "utmContent": " Founder_One ",
}


def _campaign_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0025_campaign_links.py"
    spec = importlib.util.spec_from_file_location("campaign_links_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_managed_migration_temporarily_grants_executor_schema_create(monkeypatch):
    migration = _campaign_migration()
    statements = []
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "self-managed")
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(str(statement)))

    migration.upgrade()

    assert statements[0] == "GRANT CREATE ON SCHEMA public TO flare_job_executor"
    assert "ALTER FUNCTION public.guard_campaign_link_limit() OWNER TO flare_job_executor" in statements[1]
    assert statements[-1] == "REVOKE CREATE ON SCHEMA public FROM flare_job_executor"


def test_managed_migration_keeps_schema_grants_unchanged(monkeypatch):
    migration = _campaign_migration()
    statements = []
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "yandex")
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(str(statement)))

    migration.upgrade()

    assert len(statements) == 1
    assert "OWNER TO flare_owner" in statements[0]
    assert "GRANT CREATE ON SCHEMA" not in statements[0]
    assert "REVOKE CREATE ON SCHEMA" not in statements[0]


@pytest.mark.parametrize("value", ["", " ", "bad value", "bad/path", "%61", "é", "a" * 81, None, 1])
def test_utm_values_are_bounded_and_canonical(value):
    with pytest.raises(InvalidCampaignLink):
        normalize_utm(value)


def test_campaign_helpers_normalize_without_creating_open_redirects():
    assert normalize_utm(" Launch-2026.10 ") == "launch-2026.10"
    assert normalize_utm(" ", optional=True) is None
    assert normalize_label("  Founder launch  ") == "Founder launch"
    for path in ("/", "/register", "/login"):
        assert validate_destination(path) == path
    for path in ("https://evil.example", "//evil.example", "/register?next=x", "/settings", ""):
        with pytest.raises(InvalidCampaignLink):
            validate_destination(path)
    assert public_origin("https://flare4u.tech", "http://ignored") == "https://flare4u.tech"
    assert public_origin(None, "http://testserver/") == "http://testserver"
    for unsafe in (
        "javascript:alert(1)", "https://user:pass@example.test", "//example.test",
        "https://example.test/path",
    ):
        with pytest.raises(InvalidCampaignLink):
            public_origin(unsafe, "http://ignored")


def test_destination_query_is_deterministic_and_encoded():
    destination = SimpleNamespace(
        destination_path="/register",
        utm_source="x",
        utm_medium="organic_social",
        utm_campaign="launch-2026.10",
        utm_content="founder_one",
    )
    assert destination_url(destination) == (
        "/register?utm_source=x&utm_medium=organic_social&"
        "utm_campaign=launch-2026.10&utm_content=founder_one"
    )
    destination.utm_content = None
    assert destination_url(destination) == (
        "/register?utm_source=x&utm_medium=organic_social&utm_campaign=launch-2026.10"
    )


def test_generated_slugs_are_unique_and_unguessable_shape():
    values = {CampaignLinkRepository.new_slug() for _ in range(100)}
    assert len(values) == 100
    assert all(SLUG_PATTERN.fullmatch(value) for value in values)


def test_saturated_public_admission_never_reaches_database(monkeypatch):
    calls = []

    def unexpected_open(_self, _slug):
        calls.append(True)
        raise AssertionError("database opener must not run while admission is saturated")

    monkeypatch.setattr(CampaignLinkOpener, "open", unexpected_open)
    acquired = [
        campaign_api._REDIRECT_INTAKE.acquire(blocking=False)
        for _ in range(campaign_api._REDIRECT_CAPACITY)
    ]
    assert all(acquired)
    try:
        with pytest.raises(HTTPException) as raised:
            campaign_api.open_campaign_link("a" * 24, object())
        assert raised.value.status_code == 503
        assert raised.value.headers == {"Retry-After": "1"}
        assert calls == []
    finally:
        for _ in acquired:
            campaign_api._REDIRECT_INTAKE.release()


def test_invalid_public_slug_never_reaches_database(monkeypatch):
    monkeypatch.setattr(
        CampaignLinkOpener,
        "open",
        lambda *_args: (_ for _ in ()).throw(AssertionError("database opener called")),
    )
    with pytest.raises(HTTPException) as raised:
        campaign_api.open_campaign_link("not-a-slug", object())
    assert raised.value.status_code == 404


def test_counter_failure_warning_is_payload_free_and_rate_bounded(caplog, monkeypatch):
    monkeypatch.setattr(campaign_model, "_LAST_COUNT_WARNING", float("-inf"))
    monkeypatch.setattr(campaign_model.time, "monotonic", lambda: 1.0)
    caplog.set_level("WARNING", logger="app.models.campaign_links")
    campaign_model._warn_count_failure()
    campaign_model._warn_count_failure()
    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["campaign_link_count_failed"]


def test_production_campaign_links_require_canonical_frontend_origin():
    base = {
        "database_url": "postgresql://unused",
        "environment": "production",
        "cors_origins": ["https://flare4u.tech"],
        "email_verification_required": False,
    }
    with pytest.raises(RuntimeError, match="APP_PUBLIC_URL"):
        Settings(**base).validate()
    with pytest.raises(RuntimeError, match=r"HTTP\(S\) origin"):
        Settings(**base, app_public_url="https://flare4u.tech/path").validate()
    with pytest.raises(RuntimeError, match="must use HTTPS"):
        Settings(**base, app_public_url="http://flare4u.tech").validate()
    Settings(**base, app_public_url="https://flare4u.tech").validate()


def test_invalid_public_origin_is_rejected_before_create():
    calls = []

    class Links:
        def create(self, **_values):
            calls.append(True)
            raise AssertionError("row must not be committed for an invalid public origin")

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(app_public_url="https://flare4u.tech/path"),
            ),
        ),
        base_url="http://internal-api/",
    )
    payload = campaign_api.CreateCampaignLinkRequest(**PAYLOAD)
    with pytest.raises(HTTPException) as raised:
        campaign_api.create_campaign_link(payload, request, Links())
    assert raised.value.status_code == 503
    assert calls == []


def test_production_management_requires_exact_private_account_grant():
    user = AuthenticatedUser(
        f"auth:{uuid4()}", uuid4(), "founder@flare.example", "Founder",
        "owner", "Flare", True, True,
    )
    settings = SimpleNamespace(
        dev_mode=False,
        environment="production",
        developer_mail_accounts=json.dumps({user.user_id: user.email}),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    assert campaign_api._can_manage(request, user) is True
    for denied in (
        replace(user, user_id=f"auth:{uuid4()}"),
        replace(user, email="customer@example.invalid"),
        replace(user, email_verified=False),
        replace(user, legal_accepted=False),
        replace(user, role="editor"),
    ):
        assert campaign_api._can_manage(request, denied) is False
        with pytest.raises(HTTPException) as raised:
            campaign_api._owner(request, denied)
        assert raised.value.status_code == 403
        assert raised.value.detail == {
            "code": "campaign_links_forbidden",
            "message": "Campaign links are unavailable for this account.",
        }

    settings.developer_mail_accounts = None
    assert campaign_api._can_manage(request, user) is False


def test_campaign_capability_is_no_store_and_local_dev_remains_usable():
    user = AuthenticatedUser(
        "api-test|internal", uuid4(), "", "Local", "owner", "Local", True, True,
    )
    settings = SimpleNamespace(
        dev_mode=True, environment="test", developer_mail_accounts=None,
        dev_user_id=user.user_id, dev_workspace_id=user.workspace_id,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    response = SimpleNamespace(headers={})

    assert campaign_api.campaign_links_capability(request, response, user) == {"allowed": True}
    assert response.headers == {"Cache-Control": "no-store"}
    assert campaign_api.campaign_links_capability(
        request, SimpleNamespace(headers={}), replace(user, role="viewer"),
    ) == {"allowed": False}
    assert campaign_api._can_manage(
        request, replace(user, user_id="api-test|outsider"),
    ) is False


def test_customer_owner_cannot_call_any_management_endpoint():
    user = AuthenticatedUser(
        f"auth:{uuid4()}", uuid4(), "customer@example.invalid", "Customer",
        "owner", "Customer", True, True,
    )
    application = FastAPI()
    application.state.settings = SimpleNamespace(
        dev_mode=False, environment="production", developer_mail_accounts=None,
    )
    application.state.database = object()
    application.include_router(campaign_api.router)
    application.dependency_overrides[verified_user] = lambda: user

    link_id = uuid4()
    with TestClient(application) as client:
        capability = client.get("/campaign-links/capability")
        assert capability.status_code == 200
        assert capability.json() == {"allowed": False}
        assert capability.headers["cache-control"] == "no-store"
        responses = (
            client.get("/campaign-links"),
            client.post("/campaign-links", json=PAYLOAD),
            client.get(f"/campaign-links/{link_id}"),
            client.patch(f"/campaign-links/{link_id}", json={"label": "No"}),
            client.post(f"/campaign-links/{link_id}/archive"),
        )

    assert {response.status_code for response in responses} == {403}
    assert all(response.json()["detail"]["code"] == "campaign_links_forbidden" for response in responses)


def _environment():
    runtime = os.getenv("DATABASE_URL")
    admin = os.getenv("TEST_DATABASE_URL")
    if not runtime or not admin:
        pytest.skip("Migrated PostgreSQL runtime/admin URLs are required")
    return ApiEnvironment(runtime, admin)


@contextmanager
def campaign_environment():
    environment = _environment()
    try:
        yield environment
    finally:
        environment.cleanup()


def _create(client, **changes):
    response = client.post("/campaign-links", json=PAYLOAD | changes)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
def test_selected_team_project_scope_and_ownership_transfer(team):
    owner, owner_client = team.account()
    team.config.developer_mail_accounts = json.dumps({owner.user_id: owner.email})
    project_id = team.create(owner, owner_client)
    personal = _create(owner_client, label="Personal campaign")
    selected_response = owner_client.post(
        "/campaign-links",
        params={"workspace": project_id},
        json=PAYLOAD | {"label": "Team campaign"},
    )
    assert selected_response.status_code == 201, selected_response.text
    selected = selected_response.json()
    assert [row["id"] for row in owner_client.get(
        "/campaign-links", params={"workspace": project_id},
    ).json()] == [selected["id"]]
    assert [row["id"] for row in owner_client.get("/campaign-links").json()] == [personal["id"]]

    member, member_client = team.account()
    token, _invitation = team.invite(owner_client, project_id, member, "editor")
    assert team.accept(member_client, token).status_code == 200
    assert member_client.get(
        "/campaign-links", params={"workspace": project_id},
    ).status_code == 403
    transfer = owner_client.post(
        f"/team/projects/{project_id}/members/{member.user_id}",
        json={"action": "transfer"},
    )
    assert transfer.status_code == 200, transfer.text
    assert owner_client.get(
        "/campaign-links", params={"workspace": project_id},
    ).status_code == 403
    new_owner_list = member_client.get(
        "/campaign-links", params={"workspace": project_id},
    )
    assert new_owner_list.status_code == 403
    team.config.developer_mail_accounts = json.dumps({member.user_id: member.email})
    new_owner_list = member_client.get(
        "/campaign-links", params={"workspace": project_id},
    )
    assert new_owner_list.status_code == 200
    assert [row["id"] for row in new_owner_list.json()] == [selected["id"]]
    renamed = member_client.patch(
        f"/campaign-links/{selected['id']}",
        params={"workspace": project_id},
        json={"label": "New owner campaign"},
    )
    assert renamed.status_code == 200, renamed.text
    archived = member_client.post(
        f"/campaign-links/{selected['id']}/archive",
        params={"workspace": project_id},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archivedAt"] is not None


@pytest.mark.integration
def test_owner_crud_cross_tenant_boundary_and_archive_redirect_semantics():
    with campaign_environment() as environment:
        workspace, owner = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=owner) as client:
            created = _create(client)
            assert environment.fetchone_admin(
                "SELECT created_by_user_id FROM public.campaign_links WHERE id=%s",
                (UUID(created["id"]),),
            ) == (owner,)
            assert set(created) == {
                "id", "label", "slug", "shortUrl", "destinationPath", "utmSource",
                "utmMedium", "utmCampaign", "utmContent", "clickCount", "createdAt",
                "archivedAt",
            }
            assert created == {
                "id": created["id"], "label": "X launch / founder post",
                "slug": created["slug"], "shortUrl": f"http://testserver/r/{created['slug']}",
                "destinationPath": "/register", "utmSource": "x",
                "utmMedium": "organic_social", "utmCampaign": "launch-2026.10",
                "utmContent": "founder_one", "clickCount": 0,
                "createdAt": created["createdAt"], "archivedAt": None,
            }
            assert client.get("/campaign-links").json() == [created]

            opened = client.get(
                f"/campaign-links/r/{created['slug']}", follow_redirects=False,
            )
            assert opened.status_code == 302
            assert opened.headers["location"] == (
                "/register?utm_source=x&utm_medium=organic_social&"
                "utm_campaign=launch-2026.10&utm_content=founder_one"
            )
            assert opened.headers["cache-control"] == "no-store"
            assert "set-cookie" not in opened.headers
            assert client.head(f"/campaign-links/r/{created['slug']}").status_code == 405
            assert client.get(f"/campaign-links/{created['id']}").json()["clickCount"] == 1
            options = client.options(
                f"/campaign-links/r/{created['slug']}",
                headers={
                    "Origin": "http://testserver",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert options.status_code == 200
            assert client.get(f"/campaign-links/{created['id']}").json()["clickCount"] == 1
            assert client.get(
                "/campaign-links/r/aaaaaaaaaaaaaaaaaaaaaaaa",
                follow_redirects=False,
            ).status_code == 404
            assert client.get(f"/campaign-links/{created['id']}").json()["clickCount"] == 1

            renamed = client.patch(
                f"/campaign-links/{created['id']}", json={"label": "Launch post"},
            )
            assert renamed.status_code == 200 and renamed.json()["label"] == "Launch post"
            archived = client.post(f"/campaign-links/{created['id']}/archive")
            assert archived.status_code == 200 and archived.json()["archivedAt"] is not None
            opened_after_archive = client.get(
                f"/campaign-links/r/{created['slug']}", follow_redirects=False,
            )
            assert opened_after_archive.status_code == 302
            assert client.get(f"/campaign-links/{created['id']}").json()["clickCount"] == 1
            # Archiving is deliberately idempotent.
            assert client.post(f"/campaign-links/{created['id']}/archive").json()["archivedAt"] == archived.json()["archivedAt"]

        other_workspace, other_owner = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=other_workspace, user_id=other_owner) as other:
            assert other.get(f"/campaign-links/{created['id']}").status_code == 404
            assert other.patch(f"/campaign-links/{created['id']}", json={"label": "Stolen"}).status_code == 404
            assert other.post(f"/campaign-links/{created['id']}/archive").status_code == 404


@pytest.mark.integration
def test_editor_viewer_revocation_and_strict_payloads():
    with campaign_environment() as environment:
        workspace, user = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=user) as client:
            created = _create(client)
            for changes in (
                {"destinationPath": "https://evil.example"},
                {"utmCampaign": "bad campaign"},
                {"utmContent": "x" * 81},
                {"label": "x\nheader"},
                {"unknown": "field"},
            ):
                response = client.post("/campaign-links", json=PAYLOAD | changes)
                assert response.status_code == 422

        for role in ("editor", "viewer"):
            environment.execute_admin(
                "UPDATE public.workspace_members SET role=%s WHERE workspace_id=%s AND user_id=%s",
                (role, workspace, user),
            )
            with environment.client(workspace_id=workspace, user_id=user) as revoked:
                assert revoked.get("/campaign-links").status_code == 403
                assert revoked.post("/campaign-links", json=PAYLOAD).status_code == 403
                assert revoked.patch(f"/campaign-links/{created['id']}", json={"label": "No"}).status_code == 403
        # The public redirect is independent of customer authentication.
        with environment.client() as anonymous_surface:
            assert anonymous_surface.get(
                f"/campaign-links/r/{created['slug']}", follow_redirects=False,
            ).status_code == 302
            assert anonymous_surface.get("/campaign-links/r/not-a-slug", follow_redirects=False).status_code == 404


@pytest.mark.integration
def test_atomic_active_cap_archive_capacity_and_concurrent_counting():
    with campaign_environment() as environment:
        workspace, owner = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=owner) as client:
            links = [_create(client, label=f"Campaign {index}", utmContent=f"post_{index}") for index in range(24)]

        database = Database(environment.runtime_url, min_size=1, max_size=4)
        database.open()
        identity = WorkspaceIdentity(workspace, owner)

        def create_boundary(index):
            repository = CampaignLinkRepository(database, identity)
            try:
                return repository.create(
                    label=f"Boundary {index}", destination_path="/", utm_source="x",
                    utm_medium="social", utm_campaign="boundary", utm_content=f"post_{index}",
                )
            except CampaignLinkLimitReached:
                return None

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                boundary = list(pool.map(create_boundary, range(2)))
            assert sum(record is not None for record in boundary) == 1
            assert len(CampaignLinkRepository(database, identity).list()) == 25

            first = UUID(links[0]["id"])
            CampaignLinkRepository(database, identity).archive(first)
            replacement = create_boundary(3)
            assert replacement is not None

            opener = CampaignLinkOpener(database)
            with ThreadPoolExecutor(max_workers=8) as pool:
                destinations = list(pool.map(lambda _: opener.open(replacement.slug), range(8)))
            assert all(destination is not None for destination in destinations)
            assert CampaignLinkRepository(database, identity).get(replacement.id).click_count == 8
        finally:
            database.close()


@pytest.mark.integration
def test_owner_list_is_bounded_without_hiding_active_links():
    with campaign_environment() as environment:
        workspace, owner = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=owner) as client:
            active = [_create(client, label=f"Active {index}") for index in range(2)]
            environment.execute_admin(
                """INSERT INTO public.campaign_links(
                       workspace_id,created_by_user_id,label,slug,destination_path,
                       utm_source,utm_medium,utm_campaign,archived_at,created_at)
                    SELECT %s,%s,'Archived '||ordinal,
                           lpad(ordinal::text,22,'a'),'/',
                           'x','social','history',clock_timestamp(),
                           clock_timestamp()-(ordinal*interval '1 second')
                      FROM generate_series(1,105) ordinal""",
                (workspace, owner),
            )
            listed = client.get("/campaign-links")
            assert listed.status_code == 200
            rows = listed.json()
            assert len(rows) == 100
            assert {row["id"] for row in active} <= {row["id"] for row in rows}


@pytest.mark.integration
def test_counter_lock_timeout_fails_open_and_runtime_privileges_are_narrow(caplog):
    with campaign_environment() as environment:
        workspace, owner = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=owner) as client:
            created = _create(client)
            caplog.set_level("WARNING", logger="app.models.campaign_links")
            with psycopg.connect(environment.admin_url) as blocker:
                blocker.execute("SELECT 1 FROM public.campaign_links WHERE id=%s FOR UPDATE", (UUID(created["id"]),))
                opened = client.get(
                    f"/campaign-links/r/{created['slug']}", follow_redirects=False,
                )
                assert opened.status_code == 302
            messages = [record.getMessage() for record in caplog.records]
            assert messages.count("campaign_link_count_failed") == 1
            assert created["slug"] not in " ".join(messages)
            assert client.get(f"/campaign-links/{created['id']}").json()["clickCount"] == 0

        with psycopg.connect(environment.runtime_url) as runtime:
            runtime.execute("SELECT set_config('app.workspace_id','',true),set_config('app.user_id','',true)")
            assert runtime.execute("SELECT count(*) FROM public.campaign_links").fetchone() == (0,)
            assert runtime.execute("SELECT has_table_privilege(current_user,'public.campaign_links','DELETE')").fetchone() == (False,)
            assert runtime.execute("SELECT has_column_privilege(current_user,'public.campaign_links','click_count','UPDATE')").fetchone() == (False,)
            assert runtime.execute("SELECT has_function_privilege(current_user,'public.campaign_link_resolve(text)','EXECUTE')").fetchone() == (True,)
            assert runtime.execute("SELECT has_function_privilege(current_user,'public.campaign_link_count(text)','EXECUTE')").fetchone() == (True,)


@pytest.mark.integration
def test_runtime_rls_checks_owner_membership_in_database():
    with campaign_environment() as environment:
        workspace, owner = uuid4(), f"campaign-owner|{uuid4()}"
        with environment.client(workspace_id=workspace, user_id=owner) as client:
            created = _create(client)

        identity = WorkspaceIdentity(workspace, owner)
        database = Database(environment.runtime_url, min_size=1, max_size=2)
        database.open()
        try:
            with database.workspace_transaction(identity) as connection:
                assert connection.execute(
                    "SELECT count(*) FROM public.campaign_links WHERE workspace_id=%s",
                    (workspace,),
                ).fetchone()["count"] == 1
                assert connection.execute("""SELECT
                    has_column_privilege(current_user,'public.campaign_links','label','INSERT') AS insert_label,
                    has_column_privilege(current_user,'public.campaign_links','archived_at','UPDATE') AS update_archive,
                    has_column_privilege(current_user,'public.campaign_links','created_by_user_id','INSERT') AS insert_creator,
                    has_column_privilege(current_user,'public.campaign_links','click_count','INSERT') AS insert_counter,
                    has_column_privilege(current_user,'public.campaign_links','created_at','INSERT') AS insert_created,
                    has_column_privilege(current_user,'public.campaign_links','destination_path','UPDATE') AS update_destination,
                    has_column_privilege(current_user,'public.campaign_links','utm_campaign','UPDATE') AS update_campaign""").fetchone() == {
                        "insert_label": True,
                        "update_archive": True,
                        "insert_creator": False,
                        "insert_counter": False,
                        "insert_created": False,
                        "update_destination": False,
                        "update_campaign": False,
                    }
                with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                    connection.execute(
                        "UPDATE public.campaign_links SET destination_path='/login' WHERE id=%s",
                        (UUID(created["id"]),),
                    )

            environment.execute_admin(
                "UPDATE public.workspace_members SET role='editor' WHERE workspace_id=%s AND user_id=%s",
                (workspace, owner),
            )
            with database.workspace_transaction(identity) as connection:
                assert connection.execute(
                    "SELECT count(*) FROM public.campaign_links WHERE workspace_id=%s",
                    (workspace,),
                ).fetchone()["count"] == 0
                with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                    connection.execute(
                        """INSERT INTO public.campaign_links(
                            id,workspace_id,created_by_user_id,label,slug,destination_path,
                            utm_source,utm_medium,utm_campaign)
                            VALUES(%s,%s,%s,'Blocked',%s,'/','x','social','blocked')""",
                        (uuid4(), workspace, owner, CampaignLinkRepository.new_slug()),
                    )
                updated = connection.execute(
                    "UPDATE public.campaign_links SET label='Blocked' WHERE id=%s",
                    (UUID(created["id"]),),
                )
                assert updated.rowcount == 0
        finally:
            database.close()


@pytest.mark.integration
def test_readiness_rejects_campaign_creator_default_or_fk_drift():
    with campaign_environment() as environment:
        for statement in (
            "ALTER TABLE public.campaign_links ALTER COLUMN created_by_user_id DROP DEFAULT",
            "ALTER TABLE public.campaign_links DROP CONSTRAINT campaign_links_created_by_user_id_fkey",
        ):
            with psycopg.connect(environment.admin_url) as connection:
                try:
                    connection.execute(statement)
                    connection.execute("SET LOCAL ROLE flare_app")
                    assert _connection_is_ready(connection) is False
                finally:
                    connection.rollback()
