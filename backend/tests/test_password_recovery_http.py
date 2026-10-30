import asyncio
from contextlib import contextmanager
import os
from threading import Event

from fastapi.testclient import TestClient
import pytest
import psycopg

from app.api.auth import AuthBodyLimit
from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthService, InvalidCredentials
from app.services import auth_service as module
from test_auth_service import auth, account  # noqa: F401
from test_password_recovery import recovery, link, NEW  # noqa: F401


@contextmanager
def browser(sender):
    configured = Settings(database_url=os.environ['DATABASE_URL'], environment='test',
        cors_origins=['https://flare.test'], app_public_url='https://flare.test', email_verification_required=False)
    with TestClient(create_app(configured, email_sender=sender), base_url='https://flare.test', headers={'Origin': 'https://flare.test'}) as client:
        yield client


@pytest.mark.integration
def test_request_does_not_wait_for_smtp_and_known_unknown_responses_match(auth):
    started, release, completed = Event(), Event(), Event()
    messages = []

    class SlowMail:
        def send(self, **_message):
            messages.append(_message)
            started.set()
            try:
                assert release.wait(5)
            finally:
                completed.set()

    email, _ = account(auth)
    with browser(SlowMail()) as client:
        try:
            known = client.post('/auth/forgot-password', json={'email': email}, headers={'Host': 'attacker.invalid'})
            assert started.wait(5)
            assert not completed.is_set(), 'HTTP waited for SMTP completion'
            assert 'https://flare.test/reset-password#token=' in messages[0]['text']
            assert 'attacker.invalid' not in messages[0]['text']
            unknown = client.post('/auth/forgot-password', json={'email': 'unknown@auth-test.invalid'})
            assert known.status_code == unknown.status_code == 202
            assert known.json() == unknown.json()
            assert known.headers['cache-control'] == 'no-store'
            assert 'set-cookie' not in known.headers
        finally:
            release.set()


@pytest.mark.integration
def test_reset_http_does_not_sign_in_or_touch_a_different_account(auth, recovery):
    service, mailbox = recovery
    email, session = account(auth)
    other_email, other_session = account(auth)
    token = link(recovery, email)
    with browser(mailbox) as client:
        client.cookies.set('flare_session', other_session)
        response = client.post('/auth/reset-password', json={'token': token, 'password': NEW})
        assert response.status_code == 200 and response.json() == {'ok': True}
        assert 'set-cookie' not in response.headers
        assert client.get('/auth/me').json()['user']['email'] == other_email
        reused = client.post('/auth/reset-password', json={'token': token, 'password': NEW})
        assert reused.status_code == 400 and reused.json()['detail']['code'] == 'password_reset_invalid'
        assert token not in reused.text and NEW not in reused.text
    with pytest.raises(InvalidCredentials):
        auth.current(session)
    assert auth.current(auth.login(email, NEW)).email == email
    assert any(m['subject'] == 'Your Flare password was changed' for m in mailbox.messages)


@pytest.mark.integration
def test_notification_failure_cannot_roll_back_a_successful_change(auth, recovery, caplog):
    _, mailbox = recovery
    email, _ = account(auth)
    token = link(recovery, email)
    class Failing:
        def send(self, **_message):
            raise RuntimeError('smtp-private-password-and-address')
    with browser(Failing()) as client:
        response = client.post('/auth/reset-password', json={'token': token, 'password': NEW})
        assert response.status_code == 200
    assert auth.current(auth.login(email, NEW)).email == email
    assert 'password_recovery_job_failed' in caplog.text
    assert 'smtp-private' not in caplog.text


@pytest.mark.integration
def test_unconfigured_global_mail_and_busy_admission_are_honest_generic_failures(auth, recovery, monkeypatch):
    _, mailbox = recovery
    with browser(mailbox) as client:
        client.app.state.email_sender = None
        for email in ['missing@auth-test.invalid', account(auth)[0]]:
            assert client.post('/auth/forgot-password', json={'email': email}).status_code == 503
        client.app.state.email_sender = mailbox
        monkeypatch.setattr(client.app.state.recovery_dispatcher, 'submit', lambda *_args: False)
        response = client.post('/auth/forgot-password', json={'email': 'missing@auth-test.invalid'})
        assert response.status_code == 429 and response.json()['detail']['code'] == 'password_recovery_busy'


@pytest.mark.integration
def test_validation_origin_and_unknown_token_do_not_echo_credentials(auth, recovery):
    _, mailbox = recovery
    with browser(mailbox) as client:
        for path in ['/auth/forgot-password', '/auth/reset-password']:
            assert client.post(path, json={}, headers={'Origin': 'https://evil.invalid'}).status_code == 403
        for body in [{'token': 'secret-token', 'password': 'hidden'}, {'token': 'a'*43, 'password': 'short'}, {'token': 'a'*43, 'password': NEW, 'user_id': 'forged'}]:
            response = client.post('/auth/reset-password', json=body)
            assert response.status_code == 422
            assert 'secret-token' not in response.text and NEW not in response.text and 'forged' not in response.text
        assert client.post('/auth/reset-password', json={'token': 'a'*43, 'password': NEW}).status_code == 400
        assert client.post('/auth/forgot-password', content=b'x' * 8193).status_code == 413


@pytest.mark.integration
def test_existing_smtp_is_used_even_when_verification_is_optional(auth, recovery, monkeypatch):
    from app import main
    _, mailbox = recovery
    monkeypatch.setattr(main, 'SmtpEmailSender', lambda *_args: mailbox)
    configured = Settings(database_url=os.environ['DATABASE_URL'], environment='test',
        cors_origins=['https://flare.test'], app_public_url='https://flare.test', email_verification_required=False,
        smtp_url='smtp://localhost:1025', email_from='test@flare.test')
    with TestClient(create_app(configured)) as client:
        assert client.app.state.email_sender is mailbox


@pytest.mark.integration
def test_incomplete_smtp_configuration_does_not_accept_a_recovery_request(auth, monkeypatch):
    from app import main
    monkeypatch.setattr(main, 'SmtpEmailSender', lambda *_args: pytest.fail('missing sender must not attempt SMTP'))
    configured = Settings(database_url=os.environ['DATABASE_URL'], environment='test',
        cors_origins=['https://flare.test'], app_public_url='https://flare.test', email_verification_required=False,
        smtp_url='smtp://localhost:1025')
    with TestClient(create_app(configured), headers={'Origin':'https://flare.test'}) as client:
        assert client.post('/auth/forgot-password', json={'email':'missing@auth-test.invalid'}).status_code == 503


def test_stream_guard_bounds_real_chunked_bytes_deadline_disconnect_and_replays_once():
    async def run(messages, *, timeout=1, path='/auth/reset-password', headers=()):
        sent, consumed = [], []
        async def app(scope, receive, send):
            consumed.append(await receive())
        async def receive():
            if messages:
                return messages.pop(0)
            await asyncio.Event().wait()
        async def send(message):
            sent.append(message)
        guard = AuthBodyLimit(app)
        guard.timeout = timeout
        await guard({'type': 'http', 'method': 'POST', 'path': path, 'headers': headers}, receive, send)
        return sent, consumed

    sent, consumed = asyncio.run(run([{'type': 'http.request', 'body': b'{}', 'more_body': False}]))
    assert not sent and consumed == [{'type': 'http.request', 'body': b'{}', 'more_body': False}]
    sent, consumed = asyncio.run(run([{'type': 'http.request', 'body': b'x'*5000, 'more_body': True}, {'type': 'http.request', 'body': b'x'*5000}]))
    assert sent[0]['status'] == 413 and not consumed
    sent, consumed = asyncio.run(run([{'type': 'http.request', 'body': b'{', 'more_body': True}], timeout=.01))
    assert sent[0]['status'] == 408 and not consumed
    assert asyncio.run(run([{'type': 'http.disconnect'}])) == ([], [])
    for headers in [[(b'content-length', b'-1')], [(b'content-length', b'bad')], [(b'content-length', b'2'), (b'content-length', b'2')]]:
        sent, consumed = asyncio.run(run([], headers=headers))
        assert sent[0]['status'] == 400 and not consumed
    sent, consumed = asyncio.run(run([{'type': 'http.request', 'body': b'x'*10000}], path='/imports/packages'))
    assert not sent and len(consumed[0]['body']) == 10000


@pytest.mark.integration
def test_hash_admission_protects_login_register_and_reset_without_consuming_a_link(auth, recovery):
    _, mailbox = recovery
    email, _ = account(auth)
    token = link(recovery, email)
    with browser(mailbox) as client:
        assert module._PASSWORD_CAPACITY.acquire(blocking=False)
        assert module._PASSWORD_CAPACITY.acquire(blocking=False)
        try:
            for path, payload in [
                ('/auth/login', {'email': email, 'password': 'a-long-test-password'}),
                ('/auth/register', {'email': 'busy@auth-test.invalid', 'password': NEW, 'name': 'Busy', 'termsAccepted': True, 'privacyAccepted': True}),
                ('/auth/reset-password', {'token': token, 'password': NEW}),
            ]:
                response = client.post(path, json=payload)
                assert response.status_code == 429 and response.headers['retry-after'] == '2'
                assert 'set-cookie' not in response.headers
        finally:
            module._PASSWORD_CAPACITY.release()
            module._PASSWORD_CAPACITY.release()
        assert client.post('/auth/reset-password', json={'token': token, 'password': NEW}).status_code == 200


@pytest.mark.integration
def test_account_lock_timeout_is_retryable_and_preserves_the_link(auth, recovery):
    _, mailbox = recovery
    email, _ = account(auth)
    token = link(recovery, email)
    with browser(mailbox) as client, psycopg.connect(os.environ['TEST_DATABASE_URL']) as holder:
        holder.execute('SELECT 1 FROM auth_users WHERE email=%s FOR UPDATE', (email,))
        response = client.post('/auth/reset-password', json={'token': token, 'password': NEW})
        assert response.status_code == 429 and response.json()['detail']['code'] == 'password_recovery_busy'
        holder.rollback()
        assert client.post('/auth/reset-password', json={'token': token, 'password': NEW}).status_code == 200
