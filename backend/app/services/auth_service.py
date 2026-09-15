"""Opaque, revocable database sessions and atomic first-workspace onboarding."""

from dataclasses import dataclass
from hashlib import sha256
import re
import secrets
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from pwdlib import PasswordHash

from app.models.auth import AuthRepository
from app.models.database import Database, MembershipRequiredError, WorkspaceIdentity
from app.services.email import EmailSender, verification_message

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
    """The token is malformed, expired, unknown, consumed, or unusable."""


class EmailDeliveryFailed(Exception):
    """Verification state is durable, but the outbound message was not delivered."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    workspace_id: UUID
    email: str
    name: str
    role: str
    workspace_name: str
    email_verified: bool = True
    legal_accepted: bool = True

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
        email_sender: EmailSender | None = None,
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
        name = name.strip()
        password_hash = _PASSWORDS.hash(password)
        session_token = secrets.token_urlsafe(32)
        user_id, workspace_id = f"auth:{uuid4()}", uuid4()
        verification_token = (
            secrets.token_urlsafe(32) if self.email_verification_required else None
        )
        try:
            with self.database.connection() as connection, connection.transaction():
                repository = AuthRepository(connection)
                repository.insert_user(
                    user_id, email, password_hash, name, workspace_id
                )
                repository.insert_session(
                    token_digest(session_token),
                    user_id,
                    workspace_id,
                    self.lifetime,
                )
                if verification_token is None:
                    repository.mark_email_verified(user_id)
                else:
                    repository.insert_email_verification(
                        token_digest(verification_token),
                        user_id,
                        email,
                        self.email_verification_ttl,
                    )
        except UniqueViolation:
            # Includes racing registrations. The workspace transaction rolls back.
            raise RegistrationUnavailable from None

        # Onboarding stays durable if SMTP fails. Remove the undelivered token
        # so an immediate resend can recover; revoke the session whose raw token
        # cannot be returned to the caller.
        if verification_token is not None:
            try:
                self._deliver_verification(
                    email, verification_token, remove_on_failure=True
                )
            except EmailDeliveryFailed:
                # The raw session token is not returned after this error.
                try:
                    with self.database.connection() as connection:
                        AuthRepository(connection).revoke(token_digest(session_token))
                except Exception:
                    pass
                raise
        return session_token

    def login(self, email: str, password: str) -> str:
        with self.database.connection() as connection:
            user = AuthRepository(connection).find_user(email.strip().lower())
        valid = _PASSWORDS.verify(
            password, user["password_hash"] if user else _DUMMY_HASH
        )
        if not valid or user is None or user["disabled"]:
            raise InvalidCredentials
        if self.email_verification_required and user["email_verified_at"] is None:
            raise EmailNotVerified
        identity = WorkspaceIdentity(user["initial_workspace_id"], user["id"])
        token = secrets.token_urlsafe(32)
        with self.database.workspace_transaction(identity) as connection:
            AuthRepository(connection).insert_session(
                token_digest(token),
                user["id"],
                identity.workspace_id,
                self.lifetime,
            )
        return token

    def current(self, token: str | None) -> AuthenticatedUser:
        if not token or not _TOKEN.fullmatch(token):
            raise InvalidCredentials
        digest = token_digest(token)
        with self.database.connection() as connection, connection.transaction():
            repository = AuthRepository(connection)
            row = repository.resolve_session(digest, self.idle_seconds)
            if row is None:
                raise InvalidCredentials
            connection.execute(
                "SELECT set_config('app.user_id', %s, true), "
                "set_config('app.workspace_id', %s, true)",
                (row["user_id"], str(row["workspace_id"])),
            )
            membership = connection.execute(
                """SELECT members.role, workspaces.name AS workspace_name
                   FROM public.workspace_members AS members
                   JOIN public.workspaces AS workspaces
                     ON workspaces.id=members.workspace_id
                   WHERE members.user_id=%s AND members.workspace_id=%s""",
                (row["user_id"], row["workspace_id"]),
            ).fetchone()
            if membership is None:
                raise MembershipRequiredError
            repository.touch(digest)
            return AuthenticatedUser(**row, **membership)

    def logout(self, token: str | None) -> None:
        if token and _TOKEN.fullmatch(token):
            with self.database.connection() as connection:
                AuthRepository(connection).revoke(token_digest(token))

    def verify_email(self, token: str) -> None:
        if not token or not _TOKEN.fullmatch(token):
            raise VerificationInvalid
        with self.database.connection() as connection, connection.transaction():
            verified = AuthRepository(connection).consume_and_verify_email(
                token_digest(token)
            )
            if verified is None:
                raise VerificationInvalid

    def resend_verification(self, email: str) -> None:
        if not self.email_verification_required:
            return
        normalized = email.strip().lower()
        token: str | None = None
        with self.database.connection() as connection, connection.transaction():
            repository = AuthRepository(connection)
            user = repository.find_user(normalized, lock=True)
            if (
                user is None
                or user["disabled"]
                or user["email_verified_at"] is not None
            ):
                return
            last_created = repository.last_verification_created_at(user["id"])
            now = connection.execute("SELECT now() AS now").fetchone()["now"]
            if (
                last_created is not None
                and (now - last_created).total_seconds()
                < self.email_verification_resend
            ):
                return
            token = secrets.token_urlsafe(32)
            repository.insert_email_verification(
                token_digest(token),
                user["id"],
                normalized,
                self.email_verification_ttl,
            )
        if token is not None:
            self._deliver_verification(normalized, token, remove_on_failure=True)

    def _deliver_verification(
        self, email: str, token: str, *, remove_on_failure: bool
    ) -> None:
        try:
            if self.email_sender is None or not self.app_public_url:
                raise RuntimeError("Verification delivery is not configured")
            subject, text = verification_message(
                self.app_public_url, token, self.email_verification_ttl
            )
            self.email_sender.send(to=email, subject=subject, text=text)
        except Exception:
            if remove_on_failure:
                digest = token_digest(token)
                try:
                    with self.database.connection() as connection:
                        AuthRepository(connection).remove_email_verification(digest)
                except Exception:
                    # Never replace the stable public failure with a cleanup detail.
                    pass
            raise EmailDeliveryFailed from None
