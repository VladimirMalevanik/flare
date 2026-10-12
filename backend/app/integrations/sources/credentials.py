"""Authenticated at-rest encryption; ciphertext cannot move between tenants."""
from dataclasses import dataclass
import json
from cryptography.fernet import Fernet, MultiFernet, InvalidToken


@dataclass(frozen=True)
class CredentialScope:
    workspace_id: str
    connection_id: str
    provider: str
    user_id: str
    purpose: str = 'credentials'

    def envelope(self) -> dict:
        return {'workspace': str(self.workspace_id), 'connection': str(self.connection_id),
                'provider': self.provider, 'user': self.user_id, 'purpose': self.purpose, 'version': 2}


class CredentialUnavailable(Exception):
    pass


class CredentialCipher:
    def __init__(self, keys: tuple[str, ...]):
        if not keys or len(keys) > 3:
            raise ValueError('Invalid source encryption keys')
        try:
            self._cipher = MultiFernet([Fernet(key.encode('ascii')) for key in keys])
        except (ValueError, TypeError, UnicodeError):
            raise ValueError('Invalid source encryption keys') from None

    def encrypt(self, scope: CredentialScope, value: dict) -> str:
        if not isinstance(value, dict):
            raise CredentialUnavailable
        raw = json.dumps({'scope': scope.envelope(), 'credentials': value}, ensure_ascii=False, separators=(',', ':')).encode()
        if len(raw) > (450_000 if scope.purpose == 'cursor' else 16_000):
            raise CredentialUnavailable
        return self._cipher.encrypt(raw).decode('ascii')

    def decrypt(self, scope: CredentialScope, ciphertext: str) -> dict:
        try:
            if not isinstance(ciphertext, str) or len(ciphertext) > (620_000 if scope.purpose == 'cursor' else 24_000):
                raise CredentialUnavailable
            raw = self._cipher.decrypt(ciphertext.encode('ascii'))
            if len(raw) > (450_000 if scope.purpose == 'cursor' else 16_000):
                raise CredentialUnavailable
            value = json.loads(raw)
            if value.get('scope') != scope.envelope() or not isinstance(value.get('credentials'), dict):
                raise CredentialUnavailable
            return value['credentials']
        except (InvalidToken, ValueError, TypeError, UnicodeError, AttributeError, RecursionError):
            raise CredentialUnavailable from None
