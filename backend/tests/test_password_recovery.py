"""Recovery acceptance against real restricted-role PostgreSQL, without live mail."""
from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Event, Barrier
from uuid import uuid4

import psycopg
import pytest

from app.models.auth import AuthRepository
from app.services import auth_service as module
from app.services.auth_service import AuthService, EmailDeliveryFailed, InvalidCredentials, PasswordResetInvalid, token_digest
from test_auth_service import auth, account  # noqa: F401

pytestmark = pytest.mark.integration
NEW = "a-new-recovery-password"


class Mailbox:
    def __init__(self):
        self.messages = []

    def send(self, **message):
        self.messages.append(message)


@pytest.fixture
def recovery(auth):
    sender = Mailbox()
    service = AuthService(auth.database, email_sender=sender, app_public_url="https://flare.test")
    return service, sender


def link(recovery, email):
    service, mailbox = recovery
    service.request_password_reset(email)
    return re.search(r"#token=([A-Za-z0-9_-]{43})", mailbox.messages[-1]["text"])[1]


def allow_resend(service, email):
    with service.database.connection() as c:
        c.execute("UPDATE auth_users SET password_reset_requested_at=clock_timestamp()-interval '2 minutes' WHERE email=%s", (email,))


def test_reset_preserves_identity_and_other_account_but_revokes_every_old_session(auth, recovery):
    service, mailbox = recovery
    email, first = account(auth)
    before = auth.current(first)
    second = auth.login(email, "a-long-test-password")
    other_email, other = account(auth)
    token = link(recovery, email.upper())
    with service.database.connection() as c:
        row = c.execute("SELECT * FROM auth_password_resets WHERE user_id=%s", (before.user_id,)).fetchone()
    assert row["token_hash"] == token_digest(token) and token not in str(row)
    assert mailbox.messages[-1]["to"] == email
    assert "https://flare.test/reset-password#token=" in mailbox.messages[-1]["text"]
    assert service.reset_password(token, NEW) == email
    for old in [first, second]:
        with pytest.raises(InvalidCredentials):
            auth.current(old)
    assert auth.current(other).email == other_email
    with pytest.raises(InvalidCredentials):
        auth.login(email, "a-long-test-password")
    after = auth.current(auth.login(email, NEW))
    assert (after.user_id, after.workspace_id, after.email_verified, after.legal_accepted) == (before.user_id, before.workspace_id, before.email_verified, before.legal_accepted)
    with service.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM auth_password_resets WHERE user_id=%s", (before.user_id,)).fetchone()["n"] == 0
        assert c.execute("SELECT password_hash FROM auth_users WHERE id=%s", (before.user_id,)).fetchone()["password_hash"].startswith("$argon2id$")
    with pytest.raises(PasswordResetInvalid):
        service.reset_password(token, NEW)


def test_unknown_disabled_and_cooldown_do_not_send_more_mail(auth, recovery):
    service, mailbox = recovery
    service.request_password_reset(f"{uuid4()}@auth-test.invalid")
    assert not mailbox.messages
    email, session = account(auth)
    identity = auth.current(session)
    link(recovery, email)
    service.request_password_reset(email)
    assert len(mailbox.messages) == 1
    with service.database.connection() as c:
        c.execute("UPDATE auth_users SET disabled=true WHERE id=%s", (identity.user_id,))
    service.request_password_reset(email)
    assert len(mailbox.messages) == 1


def test_failed_delivery_keeps_cooldown_and_an_older_usable_link(auth, recovery):
    service, mailbox = recovery
    email, _ = account(auth)
    first = link(recovery, email)
    allow_resend(service, email)

    class Failing:
        calls = 0
        def send(self, **_message):
            self.calls += 1
            raise RuntimeError("provider-credential-must-not-leak")

    failing = Failing()
    service.email_sender = failing
    with pytest.raises(EmailDeliveryFailed):
        service.request_password_reset(email)
    service.request_password_reset(email)
    assert failing.calls == 1
    with service.database.connection() as c:
        rows = c.execute("SELECT token_hash FROM auth_password_resets WHERE email=%s", (email,)).fetchall()
    assert len(rows) == 2 and {"token_hash": token_digest(first)} in rows
    assert service.reset_password(first, NEW) == email


def test_a_message_accepted_before_smtp_error_still_contains_a_usable_link(auth, recovery):
    service, mailbox = recovery
    email, _ = account(auth)
    class Uncertain:
        def send(self, **message):
            mailbox.messages.append(message)
            raise RuntimeError('final SMTP acknowledgement lost')
    service.email_sender = Uncertain()
    with pytest.raises(EmailDeliveryFailed):
        service.request_password_reset(email)
    token = re.search(r'#token=([A-Za-z0-9_-]{43})', mailbox.messages[-1]['text'])[1]
    assert service.reset_password(token, NEW) == email


def test_unconfirmed_attempt_after_a_crash_does_not_fill_recovery_slots(auth, recovery):
    service, mailbox = recovery
    email, session = account(auth)
    user = auth.current(session)
    with service.database.connection() as c:
        c.execute("UPDATE auth_users SET password_reset_requested_at=clock_timestamp()-interval '2 minutes' WHERE id=%s", (user.user_id,))
        for i in range(5):
            c.execute("""INSERT INTO auth_password_resets(token_hash,user_id,email,created_at,expires_at)
                VALUES(%s,%s,%s,clock_timestamp()-interval '2 minutes',clock_timestamp()+interval '20 minutes')""", (f'{i:064x}', user.user_id, email))
    token = link(recovery, email)
    with service.database.connection() as c:
        rows = c.execute('SELECT token_hash,sent_at IS NOT NULL AS sent FROM auth_password_resets WHERE user_id=%s', (user.user_id,)).fetchall()
    assert rows == [{'token_hash': token_digest(token), 'sent': True}]


def test_max_five_links_preserves_earlier_valid_links_and_expiry_frees_space(auth, recovery):
    service, mailbox = recovery
    email, _ = account(auth)
    tokens = []
    for _ in range(5):
        allow_resend(service, email)
        tokens.append(link(recovery, email))
    allow_resend(service, email)
    service.request_password_reset(email)
    assert len(mailbox.messages) == 5
    with service.database.connection() as c:
        c.execute("UPDATE auth_password_resets SET created_at=clock_timestamp()-interval '1 hour',expires_at=clock_timestamp()-interval '1 second' WHERE token_hash=%s", (token_digest(tokens[0]),))
    with pytest.raises(PasswordResetInvalid):
        service.reset_password(tokens[0], NEW)
    link(recovery, email)
    assert len(mailbox.messages) == 6
    with service.database.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM auth_password_resets WHERE email=%s", (email,)).fetchone()["n"] == 5
    assert service.reset_password(tokens[1], NEW) == email


def test_invalid_or_other_token_family_never_hashes_a_password(auth, recovery, monkeypatch):
    service, _ = recovery
    _, session = account(auth)
    monkeypatch.setattr(module, "_PASSWORDS", type("NoHash", (), {"hash": staticmethod(lambda _: pytest.fail("invalid token reached Argon2"))})())
    for token in ["", "x", "r" * 43, session, "=" * 43]:
        with pytest.raises(PasswordResetInvalid):
            service.reset_password(token, NEW)


def test_reset_does_not_verify_email_or_change_legal_acceptance(auth, recovery):
    service, _ = recovery
    email, session = account(auth)
    user = auth.current(session)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as c:
        c.execute("UPDATE auth_users SET email_verified_at=NULL,verification_provenance='pending' WHERE id=%s", (user.user_id,))
        c.execute("DELETE FROM auth_legal_acceptances WHERE user_id=%s", (user.user_id,))
    service.reset_password(link(recovery, email), NEW)
    current = auth.current(auth.login(email, NEW))
    assert not current.email_verified and not current.legal_accepted


def test_reset_transaction_rolls_back_password_sessions_and_tokens_together(auth, recovery, monkeypatch):
    service, _ = recovery
    email, session = account(auth)
    token = link(recovery, email)
    original = AuthRepository.change_password

    def fail(repository, *args):
        assert original(repository, *args)
        raise RuntimeError("forced rollback")

    monkeypatch.setattr(AuthRepository, "change_password", fail)
    with pytest.raises(RuntimeError):
        service.reset_password(token, NEW)
    assert auth.current(session).email == email
    assert auth.current(auth.login(email, "a-long-test-password")).email == email
    with service.database.connection() as c:
        assert c.execute("SELECT 1 FROM auth_password_resets WHERE token_hash=%s", (token_digest(token),)).fetchone()


def test_login_checked_before_reset_cannot_create_a_session_after_reset(auth, recovery, monkeypatch):
    service, _ = recovery
    email, _ = account(auth)
    token = link(recovery, email)
    checked, release = Event(), Event()
    original = module._PASSWORDS

    class Passwords:
        hash = staticmethod(original.hash)
        @staticmethod
        def verify(password, password_hash):
            result = original.verify(password, password_hash)
            checked.set()
            assert release.wait(5)
            return result

    monkeypatch.setattr(module, "_PASSWORDS", Passwords())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(auth.login, email, "a-long-test-password")
        try:
            assert checked.wait(5)
            service.reset_password(token, NEW)
        finally:
            release.set()
        with pytest.raises(InvalidCredentials):
            future.result(timeout=5)


def test_two_concurrent_valid_links_only_one_changes_the_password(auth, recovery, monkeypatch):
    service, _ = recovery
    email, session = account(auth)
    first = link(recovery, email)
    allow_resend(service, email)
    second = link(recovery, email)
    barrier, original = Barrier(2), module._PASSWORDS

    class Passwords:
        verify = staticmethod(original.verify)
        @staticmethod
        def hash(password):
            barrier.wait(timeout=5)
            return original.hash(password)

    monkeypatch.setattr(module, "_PASSWORDS", Passwords())

    def reset(token, password):
        try:
            service.reset_password(token, password)
            return password
        except PasswordResetInvalid:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: reset(*args), [(first, NEW), (second, NEW + "2")]))
    winners = [r for r in results if r]
    assert len(winners) == 1
    assert auth.current(auth.login(email, winners[0])).email == email
    with pytest.raises(InvalidCredentials):
        auth.current(session)


def test_expiry_is_rechecked_after_waiting_for_the_account_lock(auth, recovery, monkeypatch):
    service, _ = recovery
    email, session = account(auth)
    token = link(recovery, email)
    waiting = Event()
    original = AuthRepository.find_user

    def find(repository, email, *, lock=False):
        if lock:
            waiting.set()
        return original(repository, email, lock=lock)

    monkeypatch.setattr(AuthRepository, "find_user", find)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.execute("SELECT 1 FROM auth_users WHERE email=%s FOR UPDATE", (email,))
        future = pool.submit(service.reset_password, token, NEW)
        try:
            assert waiting.wait(5)
            holder.execute("SELECT pg_sleep(0.05)")
            holder.execute("UPDATE auth_password_resets SET expires_at=clock_timestamp()-interval '1 millisecond' WHERE token_hash=%s", (token_digest(token),))
        finally:
            holder.commit()
        with pytest.raises(PasswordResetInvalid):
            future.result(timeout=5)
    assert auth.current(session).email == email
