"""Authentication HTTP and cross-workspace negative tests on PostgreSQL."""
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.config import Settings
from app.main import create_app
from test_auth_service import auth, account  # noqa: F401; shared DB cleanup fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def client(auth):
    configured = Settings(database_url=os.environ['DATABASE_URL'], environment='test', cors_origins=['http://testserver'])
    with TestClient(create_app(configured), headers={'Origin': 'http://testserver'}) as client:
        yield client


def register(client):
    payload = {'email': f'{uuid4()}@auth-test.invalid', 'password': 'long-secret-password', 'name': 'Real User'}
    response = client.post('/auth/register', json=payload)
    assert response.status_code == 201, response.text
    return payload, response


def test_registration_session_items_login_logout(client):
    assert client.get('/items').status_code == 401
    payload, response = register(client)
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'domain=' not in cookie
    me = client.get('/auth/me').json()
    assert me['workspace']['role'] == 'owner' and me['user']['email'] == payload['email']
    item = client.post('/items', json={'type': 'note', 'content': 'Private note'}).json()
    assert client.get('/items').json()[0]['id'] == item['id']
    token = client.cookies.get('flare_session')
    assert client.post('/auth/logout').status_code == 204
    assert client.get('/auth/me').status_code == 401
    client.cookies.set('flare_session', token)
    assert client.get('/items').status_code == 401
    client.cookies.clear()
    assert client.post('/auth/login', json={'email':payload['email'],'password':'wrong'}).status_code == 401
    assert client.post('/auth/login', json={'email':payload['email'],'password':payload['password']}).status_code == 200
    assert client.get('/auth/me').json()['workspace']['id'] == me['workspace']['id']
    assert client.get(f"/items/{item['id']}").status_code == 200


def test_foreign_items_and_forged_identity_headers(client, auth):
    register(client)
    own = client.get('/auth/me').json()
    foreign_email, foreign_token = account(auth)
    foreign = auth.current(foreign_token)
    from app.services.item_service import ItemService
    other_item = ItemService(auth.database, foreign.identity).create_note(title='Foreign', content='Foreign secret')
    headers = {'X-Workspace-Id': str(foreign.workspace_id), 'X-User-Id': foreign.user_id}
    assert client.get('/auth/me', headers=headers).json()['workspace']['id'] == own['workspace']['id']
    assert client.get(f'/items/{other_item.id}', headers=headers).status_code == 404
    assert client.delete(f'/items/{other_item.id}', headers=headers).status_code == 404
    assert client.get('/items', headers=headers).json() == []
    assert ItemService(auth.database, foreign.identity).get_item(other_item.id)


def test_revoked_membership_and_viewer(client):
    register(client)
    me = client.get('/auth/me').json()
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        conn.execute("UPDATE workspace_members SET role='viewer' WHERE user_id=%s", (me['user']['id'],))
    assert client.get('/items').status_code == 200
    assert client.post('/items', json={'type':'note','content':'No'}).status_code == 403
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        conn.execute('DELETE FROM workspace_members WHERE user_id=%s', (me['user']['id'],))
    assert client.get('/items').status_code == 403


@pytest.mark.parametrize('origin', ['', 'null', 'http://evil.invalid', 'http://testserver.evil.invalid'])
def test_origin_rejects_state_changes(client, origin):
    register(client)
    for path in ['/auth/logout', '/auth/login', '/auth/register', '/items']:
        assert client.post(path, headers={'Origin':origin}, json={}).status_code == 403
    assert client.get('/auth/me').status_code == 200


def test_duplicate_email_and_password_not_echoed(client):
    payload, _ = register(client)
    assert client.post('/auth/register', json=payload).status_code == 409
    payload['password'] = 'secret'
    response = client.post('/auth/register', json=payload)
    assert response.status_code == 422 and 'secret' not in response.text


def test_production_cookie_and_dev_rejection(auth):
    settings = Settings(
        database_url=os.environ['DATABASE_URL'],
        cors_origins=['https://flare.test'],
        email_verification_required=False,
    )
    with TestClient(create_app(settings), base_url='https://flare.test', headers={'Origin':'https://flare.test'}) as client:
        _, response = register(client)
        assert 'Secure' in response.headers['set-cookie']
        assert '__Host-flare_session=' in response.headers['set-cookie']
        assert client.get('/auth/me').status_code == 200
    settings.dev_mode = True
    with pytest.raises(RuntimeError, match='Production cannot'):
        with TestClient(create_app(settings)):
            pass


def test_bad_cookie_never_falls_back_to_dev(auth):
    user = auth.current(account(auth)[1])
    settings = Settings(database_url=os.environ['DATABASE_URL'], environment='test', cors_origins=['http://testserver'],
                        dev_mode=True, dev_workspace_id=user.workspace_id, dev_user_id=user.user_id, dev_workspace_name='Test')
    with TestClient(create_app(settings)) as client:
        assert client.get('/items').status_code == 200
        client.cookies.set('flare_session', 'invalid')
        assert client.get('/items').status_code == 401
        client.cookies.clear()
        assert client.get('/items', headers={'Authorization':'Bearer bad'}).status_code == 401
        client.cookies.set('__Host-flare_session', 'invalid')
        assert client.get('/items').status_code == 401


def test_missing_origin_and_foreign_preflight(client):
    client.headers.pop('origin')
    assert client.post('/auth/register', json={}).status_code == 403
    response = client.options('/items', headers={
        'Origin': 'https://evil.invalid',
        'Access-Control-Request-Method': 'POST',
    })
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers


def test_login_rotates_previous_browser_session(client, auth):
    payload, _ = register(client)
    old_token = client.cookies.get('flare_session')
    assert client.post('/auth/login', json={
        'email': payload['email'], 'password': payload['password'],
    }).status_code == 200
    assert client.cookies.get('flare_session') != old_token
    from app.services.auth_service import InvalidCredentials
    with pytest.raises(InvalidCredentials):
        auth.current(old_token)


def test_disabled_user_cannot_use_existing_session_or_login(client):
    payload, _ = register(client)
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as conn:
        conn.execute('UPDATE auth_users SET disabled=true WHERE email=%s', (payload['email'],))
    assert client.get('/items').status_code == 401
    assert client.post('/auth/login', json={
        'email': payload['email'], 'password': payload['password'],
    }).status_code == 401


@pytest.mark.parametrize('origins', [[], ['*'], ['http://flare.test'], ['https://flare.test/path']])
def test_production_rejects_unsafe_origins(origins):
    with pytest.raises(RuntimeError):
        Settings(database_url='postgresql://unused', cors_origins=origins).validate()


@pytest.mark.parametrize('password,status', [('eight123', 201), ('seven12', 422)])
def test_registration_password_minimum(client, password, status):
    email = f'{uuid4()}@auth-test.invalid'
    response = client.post('/auth/register', json={'email': email, 'password': password, 'name': 'Password Test'})
    assert response.status_code == status
    if status == 201:
        assert client.get('/auth/me').status_code == 200
        client.post('/auth/logout')
        assert client.post('/auth/login', json={'email': email, 'password': password}).status_code == 200
