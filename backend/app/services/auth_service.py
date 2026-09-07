"""Opaque, revocable database sessions and atomic first-workspace onboarding."""
from dataclasses import dataclass
from hashlib import sha256
import re
import secrets
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from pwdlib import PasswordHash

from app.models.auth import AuthRepository
from app.models.database import Database, WorkspaceIdentity, MembershipRequiredError

_PASSWORDS = PasswordHash.recommended()
_DUMMY_HASH = _PASSWORDS.hash(secrets.token_urlsafe(32))
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class InvalidCredentials(Exception):
    pass


class RegistrationUnavailable(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    workspace_id: UUID
    email: str
    name: str
    role: str
    workspace_name: str

    @property
    def identity(self) -> WorkspaceIdentity:
        return WorkspaceIdentity(self.workspace_id, self.user_id)


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, database: Database, *, lifetime: int = 604800, idle_seconds: int = 86400):
        self.database = database
        self.lifetime = lifetime
        self.idle_seconds = idle_seconds

    def register(self, email: str, password: str, name: str) -> str:
        email = email.strip().lower()
        hashed = _PASSWORDS.hash(password)
        token = secrets.token_urlsafe(32)
        user_id, workspace_id = f"auth:{uuid4()}", uuid4()
        try:
            with self.database.connection() as connection, connection.transaction():
                repo = AuthRepository(connection)
                repo.insert_user(user_id, email, hashed, name.strip(), workspace_id)
                repo.insert_session(token_digest(token), user_id, workspace_id, self.lifetime)
        except UniqueViolation:
            # Includes racing registrations. The whole workspace transaction rolls back.
            raise RegistrationUnavailable from None
        return token

    def login(self, email: str, password: str) -> str:
        with self.database.connection() as connection:
            user = AuthRepository(connection).find_user(email.strip().lower())
        valid = _PASSWORDS.verify(password, user['password_hash'] if user else _DUMMY_HASH)
        if not valid or user is None or user['disabled']:
            raise InvalidCredentials
        identity = WorkspaceIdentity(user['initial_workspace_id'], user['id'])
        token = secrets.token_urlsafe(32)
        with self.database.workspace_transaction(identity) as connection:
            AuthRepository(connection).insert_session(token_digest(token), user['id'], identity.workspace_id, self.lifetime)
        return token

    def current(self, token: str | None) -> AuthenticatedUser:
        if not token or not _TOKEN.fullmatch(token):
            raise InvalidCredentials
        digest = token_digest(token)
        with self.database.connection() as connection, connection.transaction():
            repo = AuthRepository(connection)
            row = repo.resolve_session(digest, self.idle_seconds)
            if row is None:
                raise InvalidCredentials
            connection.execute(
                "SELECT set_config('app.user_id', %s, true), set_config('app.workspace_id', %s, true)",
                (row['user_id'], str(row['workspace_id'])),
            )
            membership = connection.execute(
                """SELECT m.role, w.name AS workspace_name FROM public.workspace_members m
                   JOIN public.workspaces w ON w.id=m.workspace_id
                   WHERE m.user_id=%s AND m.workspace_id=%s""",
                (row['user_id'], row['workspace_id']),
            ).fetchone()
            if membership is None:
                raise MembershipRequiredError
            repo.touch(digest)
            return AuthenticatedUser(**row, **membership)

    def logout(self, token: str | None) -> None:
        if token and _TOKEN.fullmatch(token):
            with self.database.connection() as connection:
                AuthRepository(connection).revoke(token_digest(token))
