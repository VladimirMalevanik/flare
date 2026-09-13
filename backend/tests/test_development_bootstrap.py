"""Focused unit tests for the opt-in local development identity."""

from contextlib import nullcontext
from uuid import uuid4

import app.models.database as database_module
from app.models.database import Database, WorkspaceIdentity


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, membership=None):
        self.membership = membership
        self.calls: list[tuple[str, tuple | None]] = []

    def transaction(self):
        return nullcontext()

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if "SELECT role FROM public.workspace_members" in statement:
            return _Result(self.membership)
        return _Result()


class _Pool:
    def __init__(self, connection):
        self._connection = connection

    def connection(self):
        return nullcontext(self._connection)


def _database(connection):
    database = Database.__new__(Database)
    database._pool = _Pool(connection)
    return database


def test_development_bootstrap_creates_an_active_non_login_user(monkeypatch):
    class _PasswordHasher:
        def hash(self, password):
            return f"discarded-hash:{password}"

    class _PasswordHash:
        @staticmethod
        def recommended():
            return _PasswordHasher()

    monkeypatch.setattr(database_module, "PasswordHash", _PasswordHash)
    monkeypatch.setattr(database_module.secrets, "token_urlsafe", lambda _: "random-dev-password")

    identity = WorkspaceIdentity(uuid4(), "dev-user@example.test")
    connection = _Connection()
    _database(connection).bootstrap_development_workspace(identity, "Local Flare")

    provision_calls = [call for call in connection.calls if "provision_workspace" in call[0]]
    auth_calls = [call for call in connection.calls if "INSERT INTO public.auth_users" in call[0]]
    assert provision_calls == [("SELECT public.provision_workspace(%s, %s)", (identity.workspace_id, "Local Flare"))]
    assert len(auth_calls) == 1

    statement, parameters = auth_calls[0]
    assert "ON CONFLICT (id) DO UPDATE SET disabled = false" in statement
    assert parameters == (
        identity.user_id,
        Database._development_user_email(identity.user_id),
        "discarded-hash:random-dev-password",
        "Development user",
        identity.workspace_id,
    )
    assert identity.user_id not in parameters[1]


def test_development_bootstrap_keeps_existing_membership_idempotent(monkeypatch):
    class _PasswordHasher:
        def hash(self, password):
            return password

    class _PasswordHash:
        @staticmethod
        def recommended():
            return _PasswordHasher()

    monkeypatch.setattr(database_module, "PasswordHash", _PasswordHash)
    monkeypatch.setattr(database_module.secrets, "token_urlsafe", lambda _: "discarded")

    connection = _Connection({"role": "owner"})
    _database(connection).bootstrap_development_workspace(
        WorkspaceIdentity(uuid4(), "existing-dev-user"), "Local Flare"
    )

    assert not any("provision_workspace" in statement for statement, _ in connection.calls)
    assert any("INSERT INTO public.auth_users" in statement for statement, _ in connection.calls)
