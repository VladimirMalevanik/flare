"""Opaque, revocable database sessions and atomic first-workspace onboarding."""
from dataclasses import dataclass
from hashlib import sha256
import re
import secrets
from uuid import UUID, uuid4
from app.services.email import verification_message

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

class EmailNotVerified(Exception):
    """The account exists but email verification has not been completed."""


class VerificationInvalid(Exception):
    """The token is malformed, expired, unknown or already consumed."""


class VerificationThrottled(Exception):
    """A new verification email was requested too soon."""

@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    workspace_id: UUID
    email: str
    name: str
    role: str
    workspace_name: str
    email_verified: bool = True

    @property
    def identity(self) -> WorkspaceIdentity:
        return WorkspaceIdentity(self.workspace_id, self.user_id)


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(
        self,
        database: Database,
        *,
        lifetime: int = 604800,
        idle_seconds: int = 86400,
        email_verification_required: bool = False,
        email_verification_ttl: int = 86_400,
        email_verification_resend: int = 60,
        email_sender=None,
        app_public_url: str = "",
    ):
        self.database = database
        self.lifetime = lifetime
        self.idle_seconds = idle_seconds
        self.email_verification_required = email_verification_required
        self.email_verification_ttl = email_verification_ttl
        self.email_verification_resend = email_verification_resend
        self.email_sender = email_sender
        self.app_public_url = app_public_url

    def register(self, email: str, password: str, name: str) -> str:
        email = email.strip().lower()
        hashed = _PASSWORDS.hash(password)
        token = secrets.token_urlsafe(32)
        user_id, workspace_id = f"auth:{uuid4()}", uuid4()

        verify_token: str | None = None
        if self.email_verification_required:
            verify_token = secrets.token_urlsafe(32)

        try:
            with self.database.connection() as connection, connection.transaction():
                repo = AuthRepository(connection)
                repo.insert_user(user_id, email, hashed, name.strip(), workspace_id)
                repo.insert_session(
                    token_digest(token), user_id, workspace_id, self.lifetime
                )
                if verify_token is not None:
                    repo.insert_email_verification(
                        token_digest(verify_token), user_id, email, self.email_verification_ttl
                    )
                else:
                    repo.mark_email_verified(user_id)
        except UniqueViolation:
            raise RegistrationUnavailable from None

        # Письмо — только после успешного commit.
        if verify_token is not None:
            self._send_verification(email, name.strip(), verify_token)

        return token

    def login(self, email: str, password: str) -> str:
        with self.database.connection() as connection:
            user = AuthRepository(connection).find_user(email.strip().lower())
        valid = _PASSWORDS.verify(password, user['password_hash'] if user else _DUMMY_HASH)
        if not valid or user is None or user['disabled']:
            raise InvalidCredentials
        if self.email_verification_required and user['email_verified_at'] is None:
            raise EmailNotVerified
        identity = WorkspaceIdentity(user['initial_workspace_id'], user['id'])
        token = secrets.token_urlsafe(32)
        with self.database.workspace_transaction(identity) as connection:
            AuthRepository(connection).insert_session(
                token_digest(token), user['id'], identity.workspace_id, self.lifetime
            )
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

    def verify_email(self, token: str) -> None:
        if not token or not _TOKEN.fullmatch(token):
            raise VerificationInvalid
        with self.database.connection() as connection, connection.transaction():
            repo = AuthRepository(connection)
            row = repo.consume_email_verification(token_digest(token))
            if row is None:
                raise VerificationInvalid
            repo.mark_email_verified(row["user_id"])


    def resend_verification(self, email: str) -> None:
        email = email.strip().lower()
        with self.database.connection() as connection, connection.transaction():
            repo = AuthRepository(connection)
            user = repo.find_user(email)
            if user is None or user["disabled"] or user["email_verified_at"] is not None:
                return
            last = repo.last_verification_created_at(user["id"])
            now = connection.execute("SELECT now() AS now").fetchone()["now"]
            if last is not None and (now - last).total_seconds() < self.email_verification_resend:
                return
            token = secrets.token_urlsafe(32)
            repo.insert_email_verification(
                token_digest(token), user["id"], email, self.email_verification_ttl
            )
        self._send_verification(email, user["name"], token)


    def _send_verification(self, email: str, name: str, token: str) -> None:
        if self.email_sender is None or not self.app_public_url:
            return
        subject, text = verification_message(
            self.app_public_url, token, self.email_verification_ttl // 3600 or 1
        )
        self.email_sender.send(to=email, subject=subject, text=text)
