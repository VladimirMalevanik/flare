"""Server-only GitHub App authentication and read-only repository discovery."""

from dataclasses import dataclass
from time import time
from typing import Any

import httpx
import jwt

from app.config import GitHubSettings


class GitHubProviderError(Exception):
    """GitHub rejected or returned an invalid provider response."""


class GitHubInstallationNotAuthorized(Exception):
    """The authorized GitHub user cannot access the requested installation."""


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str


@dataclass(frozen=True)
class GitHubInstallation:
    id: int
    account_id: int
    account_login: str
    account_type: str


@dataclass(frozen=True)
class GitHubRepository:
    id: int
    owner: str
    name: str
    full_name: str
    private: bool
    html_url: str


@dataclass(frozen=True)
class GitHubAuthorization:
    user: GitHubUser
    installation: GitHubInstallation


class GitHubClient:
    API_URL = "https://api.github.com"
    WEB_URL = "https://github.com"

    def __init__(self, settings: GitHubSettings, *, transport: httpx.BaseTransport | None = None):
        settings.validate()
        self._settings = settings
        self._transport = transport

    def authorize_installation(self, code: str, installation_id: int) -> GitHubAuthorization:
        user_token = self._exchange_user_code(code)
        user_payload = self._request("GET", "/user", token=user_token)
        user = self._user(user_payload)
        for page in range(1, 101):
            payload = self._request(
                "GET",
                f"/user/installations?per_page=100&page={page}",
                token=user_token,
            )
            values = payload.get("installations")
            if not isinstance(values, list):
                raise GitHubProviderError
            for value in values:
                installation = self._installation(value)
                if installation.id == installation_id:
                    return GitHubAuthorization(user=user, installation=installation)
            if len(values) < 100:
                break
        raise GitHubInstallationNotAuthorized

    def installation(self, installation_id: int) -> GitHubInstallation:
        payload = self._request(
            "GET",
            f"/app/installations/{installation_id}",
            token=self._app_jwt(),
        )
        installation = self._installation(payload)
        if installation.id != installation_id:
            raise GitHubProviderError
        return installation

    def repositories(self, installation_id: int) -> list[GitHubRepository]:
        token_payload = self._request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._app_jwt(),
            json={"permissions": {"metadata": "read"}},
        )
        installation_token = token_payload.get("token")
        if not isinstance(installation_token, str) or not installation_token:
            raise GitHubProviderError

        repositories: list[GitHubRepository] = []
        for page in range(1, 101):
            payload = self._request(
                "GET",
                f"/installation/repositories?per_page=100&page={page}",
                token=installation_token,
            )
            values = payload.get("repositories")
            if not isinstance(values, list):
                raise GitHubProviderError
            repositories.extend(self._repository(value) for value in values)
            if len(values) < 100:
                return repositories
        raise GitHubProviderError

    @staticmethod
    def _repository(value: Any) -> GitHubRepository:
        if not isinstance(value, dict):
            raise GitHubProviderError
        owner = value.get("owner")
        if (
            type(value.get("id")) is not int
            or not isinstance(value.get("name"), str)
            or not isinstance(value.get("full_name"), str)
            or type(value.get("private")) is not bool
            or not isinstance(value.get("html_url"), str)
            or not isinstance(owner, dict)
            or not isinstance(owner.get("login"), str)
        ):
            raise GitHubProviderError
        return GitHubRepository(
            id=value["id"],
            owner=owner["login"],
            name=value["name"],
            full_name=value["full_name"],
            private=value["private"],
            html_url=value["html_url"],
        )

    def _exchange_user_code(self, code: str) -> str:
        payload = self._request(
            "POST",
            "/login/oauth/access_token",
            base_url=self.WEB_URL,
            accept="application/json",
            json={
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "code": code,
            },
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise GitHubProviderError
        return token

    @staticmethod
    def _user(value: Any) -> GitHubUser:
        if (
            not isinstance(value, dict)
            or type(value.get("id")) is not int
            or not isinstance(value.get("login"), str)
            or not value["login"]
        ):
            raise GitHubProviderError
        return GitHubUser(id=value["id"], login=value["login"])

    def _installation(self, value: Any) -> GitHubInstallation:
        if not isinstance(value, dict):
            raise GitHubProviderError
        account = value.get("account")
        if (
            type(value.get("id")) is not int
            or type(value.get("app_id")) is not int
            or value["app_id"] != self._settings.app_id
            or not isinstance(account, dict)
            or type(account.get("id")) is not int
            or not isinstance(account.get("login"), str)
            or not account["login"]
            or not isinstance(account.get("type"), str)
        ):
            raise GitHubProviderError
        return GitHubInstallation(
            id=value["id"],
            account_id=account["id"],
            account_login=account["login"],
            account_type=account["type"],
        )

    def _app_jwt(self) -> str:
        issued = int(time())
        try:
            return jwt.encode(
                {"iat": issued - 60, "exp": issued + 540, "iss": str(self._settings.app_id)},
                self._settings.private_key,
                algorithm="RS256",
            )
        except Exception:
            raise GitHubProviderError from None

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: dict[str, Any] | None = None,
        base_url: str | None = None,
        accept: str = "application/vnd.github+json",
    ) -> dict[str, Any]:
        try:
            with httpx.Client(
                base_url=base_url or self.API_URL,
                timeout=10,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                headers = {
                    "Accept": accept,
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                if token is not None:
                    headers["Authorization"] = f"Bearer {token}"
                response = client.request(
                    method,
                    path,
                    headers=headers,
                    json=json,
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise GitHubProviderError from None
        if not isinstance(payload, dict):
            raise GitHubProviderError
        return payload
