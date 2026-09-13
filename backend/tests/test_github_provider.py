import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import GitHubSettings
from app.integrations.github import GitHubClient, GitHubProviderError


def test_app_jwt_is_short_lived_rs256_and_contains_required_claims():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    settings = GitHubSettings(
        123, "flare-test", pem, "https://flare.test/sources",
        client_id="Iv1.test", client_secret="client-secret",
    )

    token = GitHubClient(settings)._app_jwt()
    payload = jwt.decode(
        token,
        private_key.public_key(),
        algorithms=["RS256"],
        issuer="123",
    )

    assert payload["exp"] - payload["iat"] == 600


def test_installation_repository_boundary_uses_ephemeral_read_only_token(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if request.url.path == "/app/installations/42":
            return httpx.Response(200, json={
                "id": 42, "app_id": 123,
                "account": {"id": 7, "login": "acme", "type": "Organization"},
            })
        if request.url.path == "/app/installations/42/access_tokens":
            assert json.loads(request.content) == {"permissions": {"metadata": "read"}}
            return httpx.Response(201, json={"token": "installation-secret"})
        assert request.url.path == "/installation/repositories"
        assert request.headers["Authorization"] == "Bearer installation-secret"
        return httpx.Response(200, json={"repositories": [{
            "id": 101, "owner": {"login": "acme"}, "name": "flare",
            "full_name": "acme/flare", "private": True,
            "html_url": "https://github.com/acme/flare",
        }]})

    settings = GitHubSettings(
        123, "flare-test", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
        "https://flare.test/sources",
        client_id="Iv1.test",
        client_secret="client-secret",
    )
    client = GitHubClient(settings, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client, "_app_jwt", lambda: "app-jwt")

    assert client.installation(42).account_login == "acme"
    assert client.repositories(42)[0].full_name == "acme/flare"
    assert calls[0].headers["Authorization"] == "Bearer app-jwt"
    assert calls[1].headers["Authorization"] == "Bearer app-jwt"


def test_installation_requires_the_configured_github_app_id(monkeypatch):
    def handler(request: httpx.Request):
        assert request.url.path == "/app/installations/42"
        return httpx.Response(200, json={
            "id": 42,
            "account": {"id": 7, "login": "acme", "type": "Organization"},
        })

    settings = GitHubSettings(
        123, "flare-test", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
        "https://flare.test/sources",
        client_id="Iv1.test",
        client_secret="client-secret",
    )
    client = GitHubClient(settings, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client, "_app_jwt", lambda: "app-jwt")

    with pytest.raises(GitHubProviderError):
        client.installation(42)


def test_user_authorization_binds_requested_installation_to_verified_identity():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if request.url.path == "/login/oauth/access_token":
            assert request.headers["Accept"] == "application/json"
            assert json.loads(request.content) == {
                "client_id": "Iv1.test", "client_secret": "client-secret", "code": "one-time-code",
            }
            return httpx.Response(200, json={"access_token": "ephemeral-user-token"})
        assert request.headers["Authorization"] == "Bearer ephemeral-user-token"
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 501, "login": "octocat"})
        assert request.url.path == "/user/installations"
        return httpx.Response(200, json={"installations": [{
            "id": 42, "app_id": 123,
            "account": {"id": 7, "login": "acme", "type": "Organization"},
        }]})

    settings = GitHubSettings(
        123, "flare-test", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
        "https://flare.test/sources",
        client_id="Iv1.test",
        client_secret="client-secret",
    )
    client = GitHubClient(settings, transport=httpx.MockTransport(handler))

    authorization = client.authorize_installation("one-time-code", 42)

    assert authorization.user.id == 501
    assert authorization.user.login == "octocat"
    assert authorization.installation.id == 42
    assert [call.url.host for call in calls] == ["github.com", "api.github.com", "api.github.com"]
