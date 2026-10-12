"""Fixed-host, nonredirecting and bounded provider HTTP transport."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import time
from urllib.parse import urlsplit
import httpx
from .contracts import SourceProviderError
from .settings import SourceSettings

HOSTS = frozenset({'slack.com', 'gmail.googleapis.com', 'www.googleapis.com',
                  'oauth2.googleapis.com', 'api.notion.com', 'api.github.com'})


def retry_delay(headers: dict, default: int = 60) -> int:
    value = headers.get('retry-after')
    try:
        if value is not None:
            try:
                return max(1, math.ceil(float(value)))
            except ValueError:
                return max(1, math.ceil(parsedate_to_datetime(value).timestamp() - time.time()))
        reset = headers.get('x-ratelimit-reset')
        if reset:
            return max(1, math.ceil(float(reset) - time.time()))
    except (ValueError, TypeError, OverflowError):
        pass
    return default


@dataclass(frozen=True)
class ProviderResponse:
    status: int
    headers: dict = field(repr=False)
    data: bytes = field(repr=False)

    def checked(self):
        if self.status == 429 or self.status == 403 and self.headers.get('x-ratelimit-remaining') == '0':
            raise SourceProviderError('rate_limited', retry_after=retry_delay(self.headers))
        if self.status in (401, 403):
            raise SourceProviderError('authorization_lost', reconnect=True)
        if self.status == 404:
            raise SourceProviderError('resource_unavailable')
        if not 200 <= self.status < 300:
            raise SourceProviderError('provider_unavailable', retry_after=60 if self.status >= 500 else None)
        return self

    def json(self) -> dict | list:
        self.checked()
        try:
            value = json.loads(self.data)
            if not isinstance(value, (dict, list)):
                raise ValueError
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise SourceProviderError('invalid_provider_response') from None


class ProviderHTTP:
    def __init__(self, settings: SourceSettings, *, transport=None, clock=time.monotonic):
        self.settings, self.transport, self.clock = settings, transport, clock
        self.started, self.requests = clock(), 0

    def request(self, method: str, url: str, *, headers=None, params=None, data=None, json_body=None, auth=None) -> ProviderResponse:
        try:
            parsed = urlsplit(url)
            safe = parsed.scheme == 'https' and parsed.hostname in HOSTS and not parsed.username and not parsed.password and not parsed.fragment and parsed.port in (None,443)
        except (ValueError, TypeError):
            safe = False
        if not safe:
            raise SourceProviderError('invalid_provider_request')
        if self.requests >= self.settings.max_requests or self.clock() - self.started >= self.settings.deadline_seconds:
            raise SourceProviderError('sync_budget_reached')
        if parsed.hostname == "api.notion.com" and self.requests:
            time.sleep(0.35)
        self.requests += 1
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(10, connect=5), follow_redirects=False, trust_env=False) as client:
                with client.stream(method, url, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity', **(headers or {})}, params=params, data=data, json=json_body, auth=auth) as response:
                    if response.headers.get('content-encoding', 'identity').lower() not in ('identity', ''):
                        raise SourceProviderError('unsupported_response_encoding')
                    length = response.headers.get('content-length')
                    if length and int(length) > self.settings.max_response_bytes:
                        raise SourceProviderError('response_too_large')
                    if response.is_stream_consumed:
                        chunks = (response.content,)
                    else:
                        chunks = response.iter_raw()
                    body = bytearray()
                    for chunk in chunks:
                        if self.clock() - self.started >= self.settings.deadline_seconds:
                            raise SourceProviderError('sync_budget_reached')
                        if len(body) + len(chunk) > self.settings.max_response_bytes:
                            raise SourceProviderError('response_too_large')
                        body.extend(chunk)
                    return ProviderResponse(response.status_code, dict(response.headers), bytes(body))
        except SourceProviderError:
            raise
        except (httpx.HTTPError, ValueError, OverflowError):
            raise SourceProviderError('provider_unavailable', retry_after=60) from None


def plain_text(value: object, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or '\x00' in value or len(value.encode('utf-8')) > maximum or not allow_empty and not value.strip():
        raise SourceProviderError('invalid_provider_response')
    return value


def identifier(value: object) -> str:
    text = plain_text(value, maximum=300)
    if any(ch in text for ch in ('/', '\\', '?', '#', '\r', '\n')) or text in ('.', '..'):
        raise SourceProviderError('invalid_provider_response')
    return text


def next_cursor(value: object) -> str | None:
    # Opaque provider cursors are never parsed or used as URLs.
    if value is None or value == '':
        return None
    return plain_text(value, maximum=6000)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
