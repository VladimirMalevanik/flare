"""Touch-only validation. No URL, query, identity, or browser fingerprint persistence."""
from hashlib import sha256
import hmac
import re
import secrets
import time
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

_FIELDS = frozenset(('utm_source','utm_medium','utm_campaign','utm_content','ref','referrer_domain','landing_route'))
_VALUE = re.compile(r'[a-z0-9/._-]{1,80}\Z')
_NETWORK_KEY = secrets.token_bytes(32)


def normalize_touch(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value or value.keys() - _FIELDS:
        raise ValueError('Invalid touch')
    result = {}
    for key, text in value.items():
        if not isinstance(text, str) or len(text)>80 or not _VALUE.fullmatch(text.strip().lower()):
            raise ValueError('Invalid touch field')
        result[key] = text.strip().lower()
    if result.get('landing_route') not in ('/', '/login', '/register'):
        raise ValueError('Invalid landing route')
    return result


def reference_digest(reference: str | None) -> str | None:
    try:
        if reference is None or str(UUID(reference)) != reference:
            return None
        return sha256(reference.encode()).hexdigest()
    except (ValueError, TypeError, AttributeError):
        return None


def network_digest(peer: str) -> str:
    # Rotating process-local pseudonym, never retain/log the peer. Only actual
    # socket identity is used; forwarded headers cannot select a new bucket.
    return hmac.new(_NETWORK_KEY, f'{int(time.time()//3600)}:{peer}'.encode(), 'sha256').hexdigest()


class AttributionService:
    def __init__(self, database):
        self.database = database

    def policy(self) -> dict:
        with self.database.connection() as c:
            c.execute("SET LOCAL statement_timeout='500ms'")
            return c.execute('SELECT public.acquisition_policy() AS policy').fetchone()['policy']

    def touch(self, *, reference: str | None, peer: str, touch: object, revision: str, deadline_ms: int = 500) -> str | None:
        normalized = normalize_touch(touch)
        # Unissued/invalid references cannot select arbitrary existing state.
        is_new = not reference_digest(reference)
        reference = str(uuid4()) if is_new else reference
        with self.database.connection() as c:
            c.execute("SET LOCAL statement_timeout='500ms'")
            c.execute("SELECT set_config('statement_timeout',%s,true)",(f'{max(10,min(deadline_ms,500))}ms',))
            accepted = c.execute('SELECT public.acquisition_touch(%s,%s,%s,%s,%s) AS accepted',
                (reference_digest(reference),network_digest(peer),Jsonb(normalized),revision,is_new)).fetchone()['accepted']
        return reference if accepted else None
