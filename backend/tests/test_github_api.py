"""GitHub connection API acceptance tests with the real RLS runtime role."""

from hashlib import sha256
import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import GitHubSettings, Settings
from app.integrations.github import (
    GitHubAuthorization,
    GitHubInstallation,
    GitHubInstallationNotAuthorized,
    GitHubRepository,
    GitHubUser,
)
from app.main import create_app

pytestmark = pytest.mark.integration


class FakeGitHubClient:
    def __init__(self):
        self.installation_calls: list[int] = []
        self.authorization_calls: list[tuple[str, int]] = []
        self.repository_calls: list[int] = []
        self.authorized_installations = {9001}
        self.available = [
            GitHubRepository(101, "acme", "flare", "acme/flare", True, "https://github.com/acme/flare"),
            GitHubRepository(202, "acme", "docs", "acme/docs", False, "https://github.com/acme/docs"),
        ]

    def authorize_installation(self, code: str, installation_id: int) -> GitHubAuthorization:
        self.authorization_calls.append((code, installation_id))
        if code != "valid-code" or installation_id not in self.authorized_installations:
            raise GitHubInstallationNotAuthorized
        return GitHubAuthorization(
            GitHubUser(501, "octocat"),
            GitHubInstallation(installation_id, 77, "acme", "Organization"),
        )

    def installation(self, installation_id: int) -> GitHubInstallation:
        self.installation_calls.append(installation_id)
        return GitHubInstallation(installation_id, 77, "acme", "Organization")

    def repositories(self, installation_id: int) -> list[GitHubRepository]:
        self.repository_calls.append(installation_id)
        return list(self.available)


@pytest.fixture
def github_environment():
    runtime, admin = os.getenv("DATABASE_URL"), os.getenv("TEST_DATABASE_URL")
    if not runtime or not admin:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for GitHub API tests")
    emails: list[str] = []
    clients: list[TestClient] = []

    def make_client(*, authenticated: bool = True):
        configured = Settings(database_url=runtime, environment="test", cors_origins=["http://testserver"])
        application = create_app(configured)
        provider = FakeGitHubClient()
        application.state.github_settings = GitHubSettings(
            app_id=123,
            app_slug="flare-test",
            private_key="-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
            frontend_return_url="http://testserver/sources",
            client_id="Iv1.test",
            client_secret="client-secret",
        )
        application.state.github_client = provider
        client = TestClient(application, headers={"Origin": "http://testserver"})
        client.__enter__()
        clients.append(client)
        if authenticated:
            email = f"{uuid4()}@github-test.invalid"
            emails.append(email)
            response = client.post("/auth/register", json={
                "email": email, "password": "password", "name": "GitHub Test",
                "termsAccepted": True, "privacyAccepted": True,
            })
            assert response.status_code == 201, response.text
        return client, provider

    yield make_client

    for client in reversed(clients):
        client.__exit__(None, None, None)
    with psycopg.connect(admin) as connection:
        rows = connection.execute(
            "SELECT id, initial_workspace_id FROM auth_users WHERE email = ANY(%s)",
            (emails,),
        ).fetchall()
        user_ids = [row[0] for row in rows]
        workspace_ids = [row[1] for row in rows]
        if workspace_ids:
            connection.execute("DELETE FROM github_connection_states WHERE workspace_id = ANY(%s)", (workspace_ids,))
            connection.execute("DELETE FROM github_connections WHERE workspace_id = ANY(%s)", (workspace_ids,))
            connection.execute("DELETE FROM auth_sessions WHERE workspace_id = ANY(%s)", (workspace_ids,))
            connection.execute("DELETE FROM workspace_members WHERE workspace_id = ANY(%s)", (workspace_ids,))
            connection.execute("DELETE FROM auth_users WHERE id = ANY(%s)", (user_ids,))
            connection.execute("DELETE FROM workspaces WHERE id = ANY(%s)", (workspace_ids,))


def start_state(client: TestClient) -> str:
    response = client.post("/integrations/github/start", json={})
    assert response.status_code == 200, response.text
    url = response.json()["authorizationUrl"]
    assert url.startswith("https://github.com/apps/flare-test/installations/new?")
    return parse_qs(urlsplit(url).query)["state"][0]


def complete(client: TestClient, state: str, installation_id: int = 9001, code: str = "valid-code"):
    return client.get(
        "/integrations/github/callback",
        params={
            "state": state, "installation_id": installation_id,
            "code": code, "setup_action": "install",
        },
        follow_redirects=False,
    )


def test_unauthenticated_user_cannot_start_connection(github_environment):
    client, _ = github_environment(authenticated=False)
    assert client.post("/integrations/github/start", json={}).status_code == 401


def test_callback_repository_selection_persistence_and_disconnect(github_environment):
    client, provider = github_environment()
    state = start_state(client)
    response = complete(client, state)
    assert response.status_code == 303
    assert response.headers["location"] == "http://testserver/sources?github=select"
    assert provider.authorization_calls == [("valid-code", 9001)]
    assert provider.installation_calls == [9001]

    pending = client.get("/integrations/github").json()
    assert pending == {"status": "pending", "accountLogin": "acme", "repository": None}
    repositories = client.get("/integrations/github/repositories")
    assert repositories.status_code == 200
    assert [repository["fullName"] for repository in repositories.json()] == ["acme/flare", "acme/docs"]
    assert provider.repository_calls == [9001]

    inaccessible = client.post("/integrations/github/repository", json={"repositoryId": 303})
    assert inaccessible.status_code == 422
    selected = client.post("/integrations/github/repository", json={"repositoryId": 101})
    assert selected.status_code == 200
    assert selected.json()["status"] == "connected"
    assert selected.json()["repository"]["fullName"] == "acme/flare"
    assert selected.json()["repository"]["private"] is True
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        workspace_id = connection.execute(
            "SELECT workspace_id FROM github_connections WHERE installation_id = 9001"
        ).fetchone()[0]
        persisted = connection.execute(
            """SELECT installation_id, account_login, authorized_user_id,
                      authorized_user_login, status, repository_id,
                      repository_full_name, repository_private
               FROM github_connections WHERE installation_id = 9001"""
        ).fetchone()
    assert persisted == (9001, "acme", 501, "octocat", "connected", 101, "acme/flare", True)

    assert client.delete("/integrations/github").status_code == 204
    assert client.get("/integrations/github").json() == {
        "status": "disconnected", "accountLogin": None, "repository": None,
    }
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        events = connection.execute(
            """SELECT event_type, metadata FROM activity_events
               WHERE workspace_id = %s AND event_type LIKE 'github_%%'
               ORDER BY created_at, id""",
            (workspace_id,),
        ).fetchall()
    assert [row[0] for row in events] == [
        "github_connection_started",
        "github_installation_authorized",
        "github_repository_selected",
        "github_disconnected",
    ]
    assert events[2][1] == {"private": True}
    assert all("repository" not in metadata and "token" not in metadata for _, metadata in events)


def test_state_is_hashed_workspace_bound_single_use_and_expiring(github_environment):
    first, first_provider = github_environment()
    second, second_provider = github_environment()
    state = start_state(first)

    admin = os.environ["TEST_DATABASE_URL"]
    digest = sha256(state.encode()).hexdigest()
    with psycopg.connect(admin) as connection:
        stored = connection.execute(
            "SELECT token_hash, token_hash <> %s FROM github_connection_states WHERE token_hash = %s",
            (state, digest),
        ).fetchone()
    assert stored == (digest, True)

    assert complete(first, "x" * 43).status_code == 400
    assert complete(second, state).status_code == 400
    assert first_provider.installation_calls == []
    assert second_provider.installation_calls == []
    assert complete(first, state).status_code == 303
    assert complete(first, state).status_code == 400

    expired = start_state(first)
    with psycopg.connect(admin) as connection:
        connection.execute(
            """UPDATE github_connection_states
               SET created_at = now() - interval '1 hour', expires_at = now() - interval '1 second'
               WHERE token_hash = %s""",
            (sha256(expired.encode()).hexdigest(),),
        )
    assert complete(first, expired).status_code == 400


def test_valid_app_installation_not_authorized_for_user_is_rejected(github_environment):
    client, provider = github_environment()
    state = start_state(client)

    response = complete(client, state, installation_id=9002)

    assert response.status_code == 403
    assert provider.authorization_calls == [("valid-code", 9002)]
    assert provider.installation_calls == []
    assert client.get("/integrations/github").json()["status"] == "disconnected"
    assert complete(client, state, installation_id=9002).status_code == 400


def test_workspace_cannot_read_modify_or_attach_another_connection(github_environment):
    first, _ = github_environment()
    second, second_provider = github_environment()
    assert complete(first, start_state(first)).status_code == 303
    assert first.post("/integrations/github/repository", json={"repositoryId": 101}).status_code == 200

    second_provider.authorized_installations.clear()
    assert complete(second, start_state(second), installation_id=9001).status_code == 403
    assert second.get("/integrations/github").json()["status"] == "disconnected"
    assert second.get("/integrations/github/repositories").status_code == 404
    assert second.delete("/integrations/github").status_code == 204
    assert first.get("/integrations/github").json()["repository"]["fullName"] == "acme/flare"
