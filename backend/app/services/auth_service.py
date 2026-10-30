"""Opaque, revocable database sessions and atomic first-workspace onboarding."""

from dataclasses import dataclass
from contextlib import contextmanager
from hashlib import sha256
import re
import secrets
from threading import BoundedSemaphore
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from pwdlib import PasswordHash

from app.models.auth import AuthRepository
from app.models.database import Database, MembershipRequiredError, WorkspaceIdentity
from app.services.email import EmailSender, verification_message, password_reset_message, password_changed_message

_PASSWORDS = PasswordHash.recommended()
_DUMMY_HASH = _PASSWORDS.hash(secrets.token_urlsafe(32))
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_RESET_CAPACITY = BoundedSemaphore(2)
_PASSWORD_CAPACITY = BoundedSemaphore(2)


class InvalidCredentials(Exception):
    pass


class AuthenticationBusy(Exception):
    """Bound Argon2 memory/CPU across login, registration and recovery."""


@contextmanager
def password_work():
    if not _PASSWORD_CAPACITY.acquire(timeout=0.5):
        raise AuthenticationBusy
    try:
        yield
    finally:
        _PASSWORD_CAPACITY.release()


class RegistrationUnavailable(Exception):
    pass


class EmailNotVerified(Exception):
    """The account exists but email verification has not been completed."""


class VerificationInvalid(Exception):
    """The token is malformed, expired, unknown, consumed, or unusable."""


class EmailDeliveryFailed(Exception):
    """An outbound attempt failed; its delivery outcome may be unknown."""


class PasswordResetInvalid(Exception):
    """Unknown, expired, reused, disabled-account or malformed recovery token."""


class PasswordResetBusy(Exception):
    """Bound concurrent expensive reset hashes without consuming a valid link."""


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
        lifetime: int = 2_592_000,
        idle_seconds: int = 2_592_000,
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

    def register(self, email: str, password: str, name: str, *, acquisition_reference: str | None = None) -> str:
        email = email.strip().lower()
        name = name.strip()
        with password_work():
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
                # Savepoint isolates optional attribution failures from durable auth.
                from app.services.attribution_service import reference_digest
                try:
                    with connection.transaction():
                        previous_timeout=connection.execute("SHOW statement_timeout").fetchone()["statement_timeout"]
                        connection.execute("""SELECT set_config('statement_timeout',
                            (CASE WHEN setting::int=0 THEN 500 ELSE least(setting::int,500) END)::text,true)
                            FROM pg_settings WHERE name='statement_timeout'""")
                        connection.execute('SELECT public.acquisition_freeze(%s)',
                            (reference_digest(acquisition_reference),))
                        connection.execute("SELECT set_config('statement_timeout',%s,true)",(previous_timeout,))
                except Exception:
                    pass
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
        with password_work():
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
            repository = AuthRepository(connection)
            current = repository.find_user(user["email"], lock=True)
            # Reset may have committed while the old password was being checked.
            # Revoke-before-insert must not resurrect an old credential session.
            if (current is None or current["id"] != user["id"] or current["disabled"]
                    or current["password_hash"] != user["password_hash"]):
                raise InvalidCredentials
            if self.email_verification_required and current["email_verified_at"] is None:
                raise EmailNotVerified
            repository.insert_session(
                token_digest(token),
                user["id"],
                identity.workspace_id,
                self.lifetime,
            )
        return token

    def request_password_reset(self, email: str) -> None:
        normalized = email.strip().lower()
        token = secrets.token_urlsafe(32)
        digest = token_digest(token)
        with self._recovery_transaction() as connection:
            repository = AuthRepository(connection)
            user = repository.find_user(normalized, lock=True)
            if user is None or user["disabled"] or not repository.insert_password_reset(digest, user):
                return
        try:
            if self.email_sender is None or not self.app_public_url:
                raise EmailDeliveryFailed
            subject, text = password_reset_message(self.app_public_url, token)
            self.email_sender.send(to=normalized, subject=subject, text=text)
            with self._recovery_transaction() as connection:
                connection.execute("UPDATE public.auth_password_resets SET sent_at=clock_timestamp() WHERE token_hash=%s", (digest,))
        except Exception:
            # SMTP can accept a message before its final acknowledgement is lost.
            # Keep that link usable. The next explicit request may retire an
            # unconfirmed attempt after the cooldown, so crashes cannot fill all
            # five slots and lock recovery for the full token lifetime.
            raise EmailDeliveryFailed from None

    def reset_password(self, token: str, password: str) -> str:
        if not _TOKEN.fullmatch(token) or not 8 <= len(password) <= 128:
            raise PasswordResetInvalid
        if not _RESET_CAPACITY.acquire(blocking=False):
            raise PasswordResetBusy
        try:
            digest = token_digest(token)
            with self._recovery_transaction() as connection:
                target = AuthRepository(connection).reset_target(digest)
            if target is None:
                raise PasswordResetInvalid
            with password_work():
                password_hash = _PASSWORDS.hash(password)
            with self._recovery_transaction() as connection:
                repository = AuthRepository(connection)
                user = repository.find_user(target["email"], lock=True)
                if user is None or user["disabled"] or not repository.change_password(digest, user, password_hash):
                    raise PasswordResetInvalid
            return user["email"]
        finally:
            _RESET_CAPACITY.release()

    @contextmanager
    def _recovery_transaction(self):
        with self.database.connection(timeout=3) as connection, connection.transaction():
            connection.execute("SELECT set_config('statement_timeout','5000',true), set_config('lock_timeout','1000',true)")
            yield connection

    def notify_password_changed(self, email: str) -> None:
        if self.email_sender is not None:
            subject, text = password_changed_message()
            self.email_sender.send(to=email, subject=subject, text=text)

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
