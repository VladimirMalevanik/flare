"""Synthetic provider contracts; no personal credentials or provider traffic."""
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
import gzip
import httpx
import pytest
from cryptography.fernet import Fernet
from app.integrations.sources.settings import SourceSettings
from app.integrations.sources.credentials import CredentialCipher, CredentialScope, CredentialUnavailable
from app.integrations.sources.http import ProviderHTTP, ProviderResponse
from app.integrations.sources.oauth import SourceOAuth
from app.integrations.sources.contracts import SourceProviderError


@pytest.fixture
def source_settings():
    return SourceSettings(enabled=True, public_api_url='http://localhost:8000/api', frontend_url='http://localhost:8000/sources',
                          token_keys=(Fernet.generate_key().decode(),), google_client_id='test-google-client', google_client_secret='test-google-secret',
                          slack_client_id='test-slack-client', slack_client_secret='test-slack-secret',
                          notion_client_id='test-notion-client', notion_client_secret='test-notion-secret')


def test_source_configuration_is_independent_and_fail_closed(source_settings):
    source_settings.validate()
    assert SourceSettings().configured('gmail') is False
    for values in [{'token_keys': ()}, {'public_api_url': 'http://public.example.com'},
                   {'frontend_url': 'https://user:private@example.com/sources'}, {'max_resources': 21}, {'deadline_seconds': 1000}]:
        with pytest.raises(ValueError):
            replace(source_settings, **values).validate()
    assert 'test-google-secret' not in repr(source_settings)


@pytest.mark.parametrize('field', ['workspace_id', 'connection_id', 'provider', 'user_id'])
def test_encrypted_credentials_cannot_be_swapped(source_settings, field):
    scope = CredentialScope('w1', 'c1', 'gmail', 'user1')
    cipher = CredentialCipher(source_settings.token_keys)
    token = cipher.encrypt(scope, {'access_token': 'test-sensitive-value'})
    assert 'test-sensitive-value' not in token
    assert cipher.decrypt(scope, token)['access_token'] == 'test-sensitive-value'
    with pytest.raises(CredentialUnavailable):
        cipher.decrypt(replace(scope, **{field: 'different'}), token)


def test_credentials_support_rotation_and_reject_tampering(source_settings):
    old = source_settings.token_keys[0]; new = Fernet.generate_key().decode()
    scope = CredentialScope('w', 'c', 'notion', 'u')
    token = CredentialCipher((old,)).encrypt(scope, {'access_token': 'synthetic'})
    assert CredentialCipher((new, old)).decrypt(scope, token)['access_token'] == 'synthetic'
    with pytest.raises(CredentialUnavailable):
        CredentialCipher((new,)).decrypt(scope, token)
    with pytest.raises(CredentialUnavailable):
        CredentialCipher((old,)).decrypt(scope, token[:-10] + 'tampered')


@pytest.mark.parametrize('url', ['http://slack.com/api', 'https://evil.example/api', 'https://slack.com.evil.example/api',
                                'https://user:private@slack.com/api', 'https://slack.com:bad/api', 'https://slack.com/api#secret'])
def test_http_rejects_unsafe_destinations_without_requests(source_settings, url):
    calls = []
    client = ProviderHTTP(source_settings, transport=httpx.MockTransport(lambda r: calls.append(r)))
    with pytest.raises(SourceProviderError) as raised:
        client.request('GET', url)
    assert raised.value.code == 'invalid_provider_request' and not calls


def test_http_caps_body_and_rejects_compression_and_redirect(source_settings):
    for response, code in [
        (httpx.Response(200, stream=httpx.ByteStream(b'x' * 10_001)), 'response_too_large'),
        (httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=httpx.ByteStream(gzip.compress(b'body'))), 'unsupported_response_encoding'),
        (httpx.Response(302, headers={'Location': 'https://evil.example'}), 'provider_unavailable'),
    ]:
        calls = []
        def send(request):
            calls.append(request)
            assert request.headers['accept-encoding'] == 'identity'
            return response
        client = ProviderHTTP(replace(source_settings, max_response_bytes=10_000), transport=httpx.MockTransport(send))
        with pytest.raises(SourceProviderError) as raised:
            client.request('GET', 'https://slack.com/api/auth.test').checked()
        assert raised.value.code == code and len(calls) == 1


def test_http_request_and_absolute_budgets(source_settings):
    now = [0]
    client = ProviderHTTP(replace(source_settings, max_requests=2), clock=lambda: now[0], transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'ok': True})))
    client.request('GET', 'https://slack.com/api/auth.test'); client.request('GET', 'https://slack.com/api/auth.test')
    with pytest.raises(SourceProviderError) as raised:
        client.request('GET', 'https://slack.com/api/auth.test')
    assert raised.value.code == 'sync_budget_reached'
    client.requests = 0; now[0] = 121
    with pytest.raises(SourceProviderError):
        client.request('GET', 'https://slack.com/api/auth.test')


def test_provider_throttling_retains_the_provider_delay_and_redacts_body():
    with pytest.raises(SourceProviderError) as raised:
        ProviderResponse(429, {'retry-after': '121'}, b'PRIVATE_CONTENT_OR_CREDENTIAL').checked()
    assert raised.value.retry_after == 121
    assert 'PRIVATE' not in str(raised.value)
    with pytest.raises(SourceProviderError) as raised:
        ProviderResponse(403, {'x-ratelimit-remaining': '0', 'retry-after': '61'}, b'private').checked()
    assert raised.value.code == 'rate_limited' and raised.value.retry_after == 61


@pytest.mark.parametrize('provider', ['gmail', 'drive', 'slack', 'notion'])
def test_oauth_urls_request_only_the_intended_read_context(source_settings, provider):
    flow = SourceOAuth(provider, source_settings, ProviderHTTP(source_settings))
    query = parse_qs(urlsplit(flow.authorize_url('test-state', 'a'*64)).query)
    assert query['state'] == ['test-state']
    assert query['redirect_uri'] == [source_settings.callback(provider)]
    assert not any(secret in str(query) for secret in ['test-google-secret', 'test-slack-secret', 'test-notion-secret'])
    if provider in ('gmail', 'drive'):
        assert query['code_challenge_method'] == ['S256']
        assert 'readonly' in query['scope'][0] and 'modify' not in query['scope'][0]
    if provider == 'slack':
        assert query['user_scope'] == ['channels:read,channels:history']


def test_gmail_exchange_and_refresh_keep_account_binding(source_settings):
    calls = []
    def send(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            values = parse_qs(request.content.decode())
            if values['grant_type'] == ['authorization_code']:
                assert values['code_verifier'] == ['a'*64]
                return httpx.Response(200, json={'access_token': 'test-access', 'refresh_token': 'test-renewal', 'expires_in': 3600})
            assert values['refresh_token'] == ['test-renewal']
            return httpx.Response(200, json={'access_token': 'test-new-access', 'expires_in': 3600})
        assert request.headers['authorization'] == 'Bearer test-access'
        return httpx.Response(200, json={'emailAddress': 'test@example.invalid'})
    flow = SourceOAuth('gmail', source_settings, ProviderHTTP(source_settings, transport=httpx.MockTransport(send)))
    credentials, label = flow.exchange('test-code', 'a'*64)
    assert label == 'test@example.invalid'
    renewed = flow.refresh(credentials)
    assert renewed['account_id'] == credentials['account_id']
    assert renewed['access_token'] == 'test-new-access' and renewed['refresh_token'] == 'test-renewal'


def test_missing_google_offline_access_is_not_fake_connected_success(source_settings):
    flow = SourceOAuth('gmail', source_settings, ProviderHTTP(source_settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'access_token': 'test', 'expires_in': 3600}))))
    with pytest.raises(SourceProviderError) as raised:
        flow.exchange('test-code', 'a'*64)
    assert raised.value.code == 'offline_access_unavailable'
