"""Read-only provider OAuth. State/session binding is owned by the API repository."""
import base64
import hashlib
import time
from urllib.parse import urlencode
from .contracts import SourceProviderError
from .http import ProviderHTTP, plain_text, identifier
from .settings import SourceSettings

GOOGLE_SCOPES = {'gmail': 'https://www.googleapis.com/auth/gmail.readonly',
                 'drive': 'https://www.googleapis.com/auth/drive.readonly openid email'}


class SourceOAuth:
    def __init__(self, provider: str, settings: SourceSettings, http: ProviderHTTP):
        if provider not in ('slack', 'gmail', 'drive', 'notion') or not settings.configured(provider):
            raise SourceProviderError('source_not_enabled')
        self.provider, self.settings, self.http = provider, settings, http

    def authorize_url(self, state: str, verifier: str) -> str:
        params = {'redirect_uri': self.settings.callback(self.provider), 'state': state}
        if self.provider in GOOGLE_SCOPES:
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
            params.update(client_id=self.settings.google_client_id, response_type='code', scope=GOOGLE_SCOPES[self.provider],
                          access_type='offline', prompt='consent', include_granted_scopes='false',
                          code_challenge=challenge, code_challenge_method='S256')
            endpoint = 'https://accounts.google.com/o/oauth2/v2/auth'
        elif self.provider == 'slack':
            params.update(client_id=self.settings.slack_client_id, scope='channels:read,channels:history')
            endpoint = 'https://slack.com/oauth/v2/authorize'
        else:
            params.update(client_id=self.settings.notion_client_id, response_type='code', owner='user')
            endpoint = 'https://api.notion.com/v1/oauth/authorize'
        return endpoint + '?' + urlencode(params)

    def _token(self, *, code: str | None = None, verifier: str | None = None, refresh_token: str | None = None) -> dict:
        grant = {'grant_type': 'refresh_token', 'refresh_token': refresh_token} if refresh_token else {
            'grant_type': 'authorization_code', 'code': plain_text(code, maximum=6000),
            'redirect_uri': self.settings.callback(self.provider)}
        if self.provider in GOOGLE_SCOPES:
            grant.update(client_id=self.settings.google_client_id, client_secret=self.settings.google_client_secret)
            if not refresh_token:
                grant['code_verifier'] = plain_text(verifier, maximum=128)
            response = self.http.request('POST', 'https://oauth2.googleapis.com/token', data=grant)
        elif self.provider == 'slack':
            grant.update(client_id=self.settings.slack_client_id, client_secret=self.settings.slack_client_secret)
            response = self.http.request('POST', 'https://slack.com/api/oauth.v2.access', data=grant)
        else:
            response = self.http.request('POST', 'https://api.notion.com/v1/oauth/token', json_body=grant,
                                         auth=(self.settings.notion_client_id, self.settings.notion_client_secret))
        if response.status == 400:
            # A failed credential exchange is never a reason to replay the code.
            raise SourceProviderError('authorization_lost', reconnect=True)
        value = response.json()
        if not isinstance(value, dict) or self.provider == 'slack' and value.get('ok') is not True:
            raise SourceProviderError('authorization_lost', reconnect=True)
        access = plain_text(value.get('access_token'), maximum=6000)
        renewal = value.get('refresh_token') or refresh_token
        if renewal is not None:
            renewal = plain_text(renewal, maximum=6000)
        expires = value.get('expires_in')
        if expires is not None and (type(expires) is not int or not 0 < expires <= 31_536_000):
            raise SourceProviderError('invalid_provider_response')
        if self.provider in GOOGLE_SCOPES and not renewal or expires and not renewal:
            raise SourceProviderError('offline_access_unavailable', reconnect=True)
        credentials = {'access_token': access, 'refresh_token': renewal,
                       'expires_at': time.time() + expires if expires else None}
        return credentials | {'response': value}

    def exchange(self, code: str, verifier: str) -> tuple[dict, str]:
        value = self._token(code=code, verifier=verifier)
        payload = value.pop('response')
        if self.provider == 'slack':
            team = payload.get('team')
            if not isinstance(team, dict):
                raise SourceProviderError('invalid_provider_response')
            value['account_id'] = identifier(team.get('id'))
            value['team_id'] = value['account_id']
            label = plain_text(team.get('name'), maximum=160)
        elif self.provider == 'notion':
            value['account_id'] = identifier(payload.get('workspace_id'))
            label = plain_text(payload.get('workspace_name') or 'Notion workspace', maximum=160)
        elif self.provider == 'gmail':
            profile = self.http.request('GET', 'https://gmail.googleapis.com/gmail/v1/users/me/profile',
                                        headers={'Authorization': 'Bearer ' + value['access_token']}).json()
            if not isinstance(profile, dict):
                raise SourceProviderError('invalid_provider_response')
            label = plain_text(profile.get('emailAddress'), maximum=160)
            value['account_id'] = label.lower()
        else:
            profile = self.http.request('GET', 'https://www.googleapis.com/oauth2/v2/userinfo',
                                        headers={'Authorization': 'Bearer ' + value['access_token']}).json()
            if not isinstance(profile, dict):
                raise SourceProviderError('invalid_provider_response')
            value['account_id'] = identifier(profile.get('id'))
            label = plain_text(profile.get('email') or profile.get('name') or 'Google account', maximum=160)
        return value, label

    def refresh(self, credentials: dict) -> dict:
        renewal = credentials.get('refresh_token')
        if not renewal:
            raise SourceProviderError('authorization_lost', reconnect=True)
        result = self._token(refresh_token=plain_text(renewal, maximum=6000))
        result.pop('response')
        return credentials | result
