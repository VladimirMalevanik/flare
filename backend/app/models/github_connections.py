"""Workspace-scoped persistence for GitHub authorization metadata."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from psycopg import Connection


@dataclass(frozen=True)
class GitHubConnectionRecord:
    workspace_id: UUID
    installation_id: int
    account_id: int
    account_login: str
    account_type: str
    authorized_user_id: int
    authorized_user_login: str
    status: str
    repository_id: int | None
    repository_owner: str | None
    repository_name: str | None
    repository_full_name: str | None
    repository_private: bool | None
    repository_html_url: str | None
    connected_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GitHubConnectionRepository:
    def __init__(self, connection: Connection):
        self._connection = connection

    def create_state(self, token_hash: str, workspace_id: UUID, user_id: str, ttl_seconds: int) -> None:
        self._connection.execute(
            "DELETE FROM public.github_connection_states WHERE expires_at <= now() OR consumed_at IS NOT NULL"
        )
        self._connection.execute(
            """INSERT INTO public.github_connection_states
                   (token_hash, workspace_id, user_id, expires_at)
               VALUES (%s, %s, %s, now() + make_interval(secs => %s))""",
            (token_hash, workspace_id, user_id, ttl_seconds),
        )

    def consume_state(self, token_hash: str, workspace_id: UUID, user_id: str) -> bool:
        row = self._connection.execute(
            """UPDATE public.github_connection_states SET consumed_at = now()
               WHERE token_hash = %s AND workspace_id = %s AND user_id = %s
                 AND consumed_at IS NULL AND expires_at > now()
               RETURNING token_hash""",
            (token_hash, workspace_id, user_id),
        ).fetchone()
        return row is not None

    def get(self) -> GitHubConnectionRecord | None:
        row = self._connection.execute(
            """SELECT workspace_id, installation_id, account_id, account_login,
                      account_type, authorized_user_id, authorized_user_login,
                      status, repository_id, repository_owner,
                      repository_name, repository_full_name, repository_private,
                      repository_html_url, connected_at, created_at, updated_at
               FROM public.github_connections"""
        ).fetchone()
        return GitHubConnectionRecord(**row) if row else None

    def save_installation(
        self,
        *,
        workspace_id: UUID,
        installation_id: int,
        account_id: int,
        account_login: str,
        account_type: str,
        authorized_user_id: int,
        authorized_user_login: str,
    ) -> GitHubConnectionRecord:
        self._connection.execute(
            """INSERT INTO public.github_connections
                   (workspace_id, installation_id, account_id, account_login, account_type,
                    authorized_user_id, authorized_user_login, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
               ON CONFLICT (workspace_id) DO UPDATE SET
                   installation_id = excluded.installation_id,
                   account_id = excluded.account_id,
                   account_login = excluded.account_login,
                   account_type = excluded.account_type,
                   authorized_user_id = excluded.authorized_user_id,
                   authorized_user_login = excluded.authorized_user_login,
                   status = 'pending',
                   repository_id = NULL,
                   repository_owner = NULL,
                   repository_name = NULL,
                   repository_full_name = NULL,
                   repository_private = NULL,
                   repository_html_url = NULL,
                   connected_at = NULL,
                   updated_at = now()""",
            (
                workspace_id, installation_id, account_id, account_login, account_type,
                authorized_user_id, authorized_user_login,
            ),
        )
        record = self.get()
        if record is None:
            raise RuntimeError("GitHub installation could not be read back")
        return record

    def select_repository(
        self,
        *,
        installation_id: int,
        repository_id: int,
        owner: str,
        name: str,
        full_name: str,
        private: bool,
        html_url: str,
    ) -> GitHubConnectionRecord | None:
        row = self._connection.execute(
            """UPDATE public.github_connections SET
                   repository_id = %s,
                   repository_owner = %s,
                   repository_name = %s,
                   repository_full_name = %s,
                   repository_private = %s,
                   repository_html_url = %s,
                   status = 'connected',
                   connected_at = now(),
                   updated_at = now()
               WHERE installation_id = %s
               RETURNING workspace_id, installation_id, account_id, account_login,
                   account_type, authorized_user_id, authorized_user_login,
                   status, repository_id, repository_owner,
                   repository_name, repository_full_name, repository_private,
                   repository_html_url, connected_at, created_at, updated_at""",
            (repository_id, owner, name, full_name, private, html_url, installation_id),
        ).fetchone()
        return GitHubConnectionRecord(**row) if row else None

    def delete(self) -> bool:
        return self._connection.execute(
            "DELETE FROM public.github_connections RETURNING workspace_id"
        ).fetchone() is not None
