"""GitHub App connection use cases with workspace and state isolation."""

from hashlib import sha256
import secrets
from urllib.parse import urlencode

from app.config import GitHubSettings
from app.integrations.github import GitHubClient, GitHubInstallationNotAuthorized, GitHubRepository
from app.models.database import Database, WorkspaceIdentity
from app.models.github_connections import GitHubConnectionRecord, GitHubConnectionRepository


class InvalidGitHubState(Exception):
    pass


class GitHubConnectionNotFound(Exception):
    pass


class GitHubRepositoryUnavailable(Exception):
    pass


class GitHubConnectionService:
    def __init__(
        self,
        database: Database,
        identity: WorkspaceIdentity,
        settings: GitHubSettings,
        client: GitHubClient,
    ):
        self._database = database
        self._identity = identity
        self._settings = settings
        self._client = client

    def start(self) -> str:
        state = secrets.token_urlsafe(32)
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            GitHubConnectionRepository(connection).create_state(
                self._digest(state),
                self._identity.workspace_id,
                self._identity.user_id,
                self._settings.state_ttl_seconds,
            )
        query = urlencode({"state": state})
        return f"https://github.com/apps/{self._settings.app_slug}/installations/new?{query}"

    def complete(self, state: str, installation_id: int, code: str) -> GitHubConnectionRecord:
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            if not GitHubConnectionRepository(connection).consume_state(
                self._digest(state), self._identity.workspace_id, self._identity.user_id
            ):
                raise InvalidGitHubState
        authorization = self._client.authorize_installation(code, installation_id)
        installation = self._client.installation(installation_id)
        if authorization.installation != installation:
            raise GitHubInstallationNotAuthorized
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            return GitHubConnectionRepository(connection).save_installation(
                workspace_id=self._identity.workspace_id,
                installation_id=installation.id,
                account_id=installation.account_id,
                account_login=installation.account_login,
                account_type=installation.account_type,
                authorized_user_id=authorization.user.id,
                authorized_user_login=authorization.user.login,
            )

    def status(self) -> GitHubConnectionRecord | None:
        with self._database.workspace_transaction(self._identity) as connection:
            return GitHubConnectionRepository(connection).get()

    def repositories(self) -> list[GitHubRepository]:
        connection = self.status()
        if connection is None:
            raise GitHubConnectionNotFound
        return self._client.repositories(connection.installation_id)

    def select_repository(self, repository_id: int) -> GitHubConnectionRecord:
        connection_record = self.status()
        if connection_record is None:
            raise GitHubConnectionNotFound
        selected = next(
            (repository for repository in self._client.repositories(connection_record.installation_id)
             if repository.id == repository_id),
            None,
        )
        if selected is None:
            raise GitHubRepositoryUnavailable
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            record = GitHubConnectionRepository(connection).select_repository(
                installation_id=connection_record.installation_id,
                repository_id=selected.id,
                owner=selected.owner,
                name=selected.name,
                full_name=selected.full_name,
                private=selected.private,
                html_url=selected.html_url,
            )
        if record is None:
            raise GitHubConnectionNotFound
        return record

    def disconnect(self) -> bool:
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            return GitHubConnectionRepository(connection).delete()

    @staticmethod
    def _digest(state: str) -> str:
        return sha256(state.encode("utf-8")).hexdigest()
