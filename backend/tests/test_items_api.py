"""End-to-end item API checks against the migrated runtime database role."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


pytestmark = pytest.mark.integration


def _required_urls() -> tuple[str, str]:
    runtime_url = os.environ.get("DATABASE_URL")
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not runtime_url or not admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for item API tests")
    return runtime_url, admin_url


@pytest.fixture
def api_environment() -> Iterator["ApiEnvironment"]:
    runtime_url, admin_url = _required_urls()
    environment = ApiEnvironment(runtime_url, admin_url)
    try:
        yield environment
    finally:
        environment.cleanup()


class ApiEnvironment:
    def __init__(self, runtime_url: str, admin_url: str):
        self.runtime_url = runtime_url
        self.admin_url = admin_url
        self.workspace_ids: set[UUID] = set()

    @contextmanager
    def client(
        self,
        *,
        workspace_id: UUID | None = None,
        user_id: str | None = None,
    ) -> Iterator[TestClient]:
        selected_workspace = workspace_id or uuid4()
        selected_user = user_id or f"api-test|{uuid4()}"
        self.workspace_ids.add(selected_workspace)
        configured = Settings(
            database_url=self.runtime_url,
            cors_origins=["http://testserver"],
            dev_mode=True,
            dev_workspace_id=selected_workspace,
            dev_user_id=selected_user,
            dev_workspace_name=f"API Test {selected_workspace}",
        )
        with TestClient(create_app(configured)) as client:
            yield client

    def execute_admin(self, statement: str, parameters: tuple[object, ...]) -> None:
        with psycopg.connect(self.admin_url) as connection:
            connection.execute(statement, parameters)

    def fetchone_admin(self, statement: str, parameters: tuple[object, ...]):
        with psycopg.connect(self.admin_url) as connection:
            return connection.execute(statement, parameters).fetchone()

    def cleanup(self) -> None:
        if not self.workspace_ids:
            return
        ids = list(self.workspace_ids)
        with psycopg.connect(self.admin_url) as connection:
            # Test tenants use ready-snapshot guards. Replica mode is scoped to
            # this cleanup transaction and only rows for generated test UUIDs.
            connection.execute("SET LOCAL session_replication_role = replica")
            connection.execute(
                "DELETE FROM public.insight_sources WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "DELETE FROM public.insights WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "UPDATE public.documents SET current_version_id = NULL "
                "WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "DELETE FROM public.chunks WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "DELETE FROM public.document_versions WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "DELETE FROM public.documents WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "DELETE FROM public.workspace_members WHERE workspace_id = ANY(%s)",
                (ids,),
            )
            connection.execute(
                "DELETE FROM public.workspaces WHERE id = ANY(%s)",
                (ids,),
            )


def _create_note(client: TestClient, *, title: str = "Customer signal", content: str = "Users need faster search") -> dict:
    response = client.post(
        "/items",
        json={"type": "note", "title": title, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_note_is_persisted_atomically_and_survives_app_restart(api_environment):
    workspace_id, user_id = uuid4(), f"api-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        item = _create_note(
            client,
            title="  Interview result  ",
            content="  Founders want cited answers.  ",
        )

    assert item == {
        "id": item["id"],
        "type": "note",
        "title": "Interview result",
        "content": "Founders want cited answers.",
        "status": "ready",
        "createdAt": item["createdAt"],
        "extractedFacts": [],
        "relatedItemIds": [],
    }

    item_id = UUID(item["id"])
    persisted = api_environment.fetchone_admin(
        """SELECT d.deleted_at, v.state, v.parser_version, c.content,
                  length(v.content_hash), d.current_version_id = v.id
           FROM public.documents d
           JOIN public.document_versions v ON v.document_id = d.id
           JOIN public.chunks c ON c.document_version_id = v.id
           WHERE d.workspace_id = %s AND d.id = %s""",
        (workspace_id, item_id),
    )
    assert persisted == (None, "ready", "manual-note-v1", item["content"], 64, True)

    # A fresh app and pool can retrieve the committed row.
    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        response = client.get(f"/items/{item_id}")
        assert response.status_code == 200
        assert response.json() == item


def test_list_supports_search_type_and_limit(api_environment):
    with api_environment.client() as client:
        first = _create_note(client, title="Pricing interview", content="Annual plans feel risky")
        second = _create_note(client, title="Onboarding", content="OAuth setup is confusing")

        assert [item["id"] for item in client.get("/items").json()] == [
            second["id"],
            first["id"],
        ]
        assert client.get("/items", params={"query": "annual"}).json() == [first]
        assert client.get("/items", params={"query": "Pricing"}).json() == [first]
        assert client.get("/items", params={"query": "   "}).status_code == 422
        assert client.get("/items", params={"type": "file"}).json() == []
        assert client.get("/items", params={"limit": 1}).json() == [second]


def test_missing_title_is_derived_from_the_first_content_line(api_environment):
    long_first_line = "A customer interview revealed a recurring onboarding problem " * 2
    with api_environment.client() as client:
        response = client.post(
            "/items",
            json={"type": "note", "content": f"{long_first_line}\nMore detail"},
        )
        assert response.status_code == 201
        assert response.json()["title"] == long_first_line[:80].rstrip()


def test_items_are_isolated_between_workspaces(api_environment):
    workspace_a, workspace_b = uuid4(), uuid4()
    user_a, user_b = f"api-test|{uuid4()}", f"api-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_a, user_id=user_a) as client_a:
        item_a = _create_note(client_a, title="Alpha", content="Alpha only")
    with api_environment.client(workspace_id=workspace_b, user_id=user_b) as client_b:
        item_b = _create_note(client_b, title="Beta", content="Beta only")

    with api_environment.client(workspace_id=workspace_a, user_id=user_a) as client_a:
        assert client_a.get(f"/items/{item_b['id']}").status_code == 404
        assert client_a.get("/items").json() == [item_a]
    with api_environment.client(workspace_id=workspace_b, user_id=user_b) as client_b:
        assert client_b.get(f"/items/{item_a['id']}").status_code == 404
        assert client_b.get("/items").json() == [item_b]


def test_delete_is_soft_and_hides_the_item(api_environment):
    workspace_id = uuid4()
    with api_environment.client(workspace_id=workspace_id) as client:
        item = _create_note(client)
        response = client.delete(f"/items/{item['id']}")
        assert response.status_code == 204
        assert response.content == b""
        assert client.get(f"/items/{item['id']}").status_code == 404
        assert client.delete(f"/items/{item['id']}").status_code == 404
        assert client.get("/items").json() == []

    stored = api_environment.fetchone_admin(
        """SELECT d.deleted_at IS NOT NULL,
                  (SELECT count(*) FROM public.document_versions v WHERE v.document_id = d.id),
                  (SELECT count(*) FROM public.chunks c
                     JOIN public.document_versions v ON v.id = c.document_version_id
                    WHERE v.document_id = d.id)
           FROM public.documents d WHERE d.id = %s""",
        (UUID(item["id"]),),
    )
    assert stored == (True, 1, 1)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "note"},
        {"type": "note", "content": "   "},
        {"type": "file", "content": "Unsupported for this slice"},
        {"type": "note", "title": "   ", "content": "Valid content"},
        {"type": "note", "content": "Valid content", "status": "ready"},
        {"type": "note", "content": "x" * 200_001},
    ],
)
def test_create_validation_rejects_invalid_or_unsupported_payloads(api_environment, payload):
    with api_environment.client() as client:
        response = client.post("/items", json=payload)
        assert response.status_code == 422
        assert client.get("/items").json() == []


def test_missing_and_malformed_ids_are_distinct(api_environment):
    with api_environment.client() as client:
        assert client.get(f"/items/{uuid4()}").status_code == 404
        assert client.get("/items/not-a-uuid").status_code == 422


def test_each_request_rechecks_membership_and_write_role(api_environment):
    workspace_id, user_id = uuid4(), f"api-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        item = _create_note(client)
        api_environment.execute_admin(
            "UPDATE public.workspace_members SET role = 'viewer' "
            "WHERE workspace_id = %s AND user_id = %s",
            (workspace_id, user_id),
        )
        assert client.get(f"/items/{item['id']}").status_code == 200
        assert client.post(
            "/items",
            json={"type": "note", "content": "Viewer write"},
        ).status_code == 403
        assert client.delete(f"/items/{item['id']}").status_code == 403

        api_environment.execute_admin(
            "DELETE FROM public.workspace_members "
            "WHERE workspace_id = %s AND user_id = %s",
            (workspace_id, user_id),
        )
        assert client.get("/items").status_code == 403


def test_item_routes_fail_closed_without_explicit_dev_mode():
    runtime_url, _ = _required_urls()
    configured = Settings(database_url=runtime_url, cors_origins=[], dev_mode=False)
    with TestClient(create_app(configured)) as client:
        response = client.get("/items")
        assert response.status_code == 503
        assert "development identity is disabled" in response.json()["detail"]
