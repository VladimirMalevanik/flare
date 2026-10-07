"""Service acceptance tests use the real restricted runtime connection."""
import os
from uuid import uuid4

import psycopg
import pytest

from app.models.database import Database
from app.services.auth_service import AuthService, InvalidCredentials, RegistrationUnavailable, token_digest

pytestmark = pytest.mark.integration


@pytest.fixture
def auth():
    runtime, admin = os.getenv('DATABASE_URL'), os.getenv('TEST_DATABASE_URL')
    if not runtime or not admin:
        pytest.skip('Requires disposable migrated PostgreSQL')
    db = Database(runtime)
    db.open()
    service = AuthService(db)
    yield service
    db.close()
    # Test accounts are unique. Reuse the item cleanup for any published notes.
    from test_items_api import ApiEnvironment
    cleanup = ApiEnvironment(runtime, admin)
    with psycopg.connect(admin) as conn:
        ids = conn.execute("SELECT id,initial_workspace_id FROM auth_users WHERE email LIKE '%@auth-test.invalid'").fetchall()
        cleanup.workspace_ids.update(row[1] for row in ids)
        cleanup.user_ids.update(row[0] for row in ids)
    cleanup.cleanup()


def account(auth):
    email = f'{uuid4()}@auth-test.invalid'
    token = auth.register(email, 'a-long-test-password', 'Test User')
    return email, token


def test_register_login_logout_and_hashes(auth):
    email, token = account(auth)
    user = auth.current(token)
    assert user.email == email and user.role == 'owner' and user.email_verified
    with auth.database.connection() as conn:
        stored = conn.execute('SELECT password_hash FROM auth_users WHERE id=%s', (user.user_id,)).fetchone()
        assert stored['password_hash'].startswith('$argon2id$')
        stored = conn.execute('SELECT token_hash FROM auth_sessions WHERE user_id=%s', (user.user_id,)).fetchone()
        assert stored['token_hash'] == token_digest(token) and stored['token_hash'] != token
    second = auth.login(email.upper(), 'a-long-test-password')
    assert second != token and auth.current(second).workspace_id == user.workspace_id
    auth.logout(second)
    with pytest.raises(InvalidCredentials):
        auth.current(second)
    assert auth.current(token).user_id == user.user_id


def test_bad_password_unknown_email_and_session(auth):
    email, _ = account(auth)
    for login_email in (email, 'missing@auth-test.invalid'):
        with pytest.raises(InvalidCredentials):
            auth.login(login_email, 'wrong-password')
    for token in (None, '', 'invalid', 'x' * 43):
        with pytest.raises(InvalidCredentials):
            auth.current(token)


def test_duplicate_email_rolls_back_workspace(auth):
    email, _ = account(auth)
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        before = conn.execute('SELECT count(*) FROM workspaces').fetchone()[0]
    with pytest.raises(RegistrationUnavailable):
        auth.register(email.upper(), 'a-different-password', 'Other User')
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        assert conn.execute('SELECT count(*) FROM workspaces').fetchone()[0] == before


@pytest.mark.parametrize('update', ["expires_at=now()-interval '1 second'", "last_seen_at=now()-interval '31 days'"])
def test_session_expiration(auth, update):
    _, token = account(auth)
    with auth.database.connection() as conn:
        conn.execute(f'UPDATE auth_sessions SET {update} WHERE token_hash=%s', (token_digest(token),))
    with pytest.raises(InvalidCredentials):
        auth.current(token)


@pytest.mark.parametrize('days_away', [2, 29])
def test_returning_user_keeps_session_without_extending_absolute_expiry(auth, days_away):
    _, token = account(auth)
    with auth.database.connection() as conn:
        original = conn.execute(
            'SELECT expires_at FROM auth_sessions WHERE token_hash=%s',
            (token_digest(token),),
        ).fetchone()['expires_at']
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at=now() - %s * interval '1 day' WHERE token_hash=%s",
            (days_away, token_digest(token)),
        )
    assert auth.current(token).email_verified
    with auth.database.connection() as conn:
        stored = conn.execute(
            'SELECT expires_at,last_seen_at,now() AS now FROM auth_sessions WHERE token_hash=%s',
            (token_digest(token),),
        ).fetchone()
    assert stored['expires_at'] == original
    assert (stored['now'] - stored['last_seen_at']).total_seconds() < 10


def test_explicit_shorter_idle_policy_still_expires(auth):
    _, token = account(auth)
    with auth.database.connection() as conn:
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at=now()-interval '2 hours' WHERE token_hash=%s",
            (token_digest(token),),
        )
    shorter_policy = AuthService(auth.database, lifetime=2_592_000, idle_seconds=3600)
    with pytest.raises(InvalidCredentials):
        shorter_policy.current(token)
