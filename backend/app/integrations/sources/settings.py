"""Source settings are independent of AI, billing, SMTP and ZIP activation."""
from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit

PROVIDERS = ('slack', 'gmail', 'drive', 'notion', 'github')


@dataclass(frozen=True)
class SourceSettings:
    enabled: bool = False
    public_api_url: str = ''
    frontend_url: str = ''
    token_keys: tuple[str, ...] = field(default=(), repr=False)
    google_client_id: str = ''
    google_client_secret: str = field(default='', repr=False)
    slack_client_id: str = ''
    slack_client_secret: str = field(default='', repr=False)
    notion_client_id: str = ''
    notion_client_secret: str = field(default='', repr=False)
    # Independently configurable bounded defaults; release owner can tune them.
    max_resources: int = 20
    max_response_bytes: int = 2_000_000
    max_document_bytes: int = 100_000
    max_requests: int = 40
    page_items: int = 15
    deadline_seconds: int = 120
    sync_interval_seconds: int = 3600
    lookback_days: int = 30
    workspace_bytes: int = 500_000_000

    def validate(self) -> None:
        if not self.enabled:
            return
        for value in (self.public_api_url, self.frontend_url):
            parsed = urlsplit(value)
            local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
            if (parsed.scheme != 'https' and not (local and parsed.scheme == 'http')) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Invalid source callback configuration')
        api, frontend = urlsplit(self.public_api_url), urlsplit(self.frontend_url)
        if frontend.path not in ("", "/"):
            raise ValueError("Source frontend URL must be the authenticated origin")
        if (api.scheme, api.hostname, api.port) != (frontend.scheme, frontend.hostname, frontend.port):
            raise ValueError('Source callbacks must return through the same authenticated origin')
        if not self.token_keys or len(self.token_keys) > 3:
            raise ValueError('Source encryption keys are required')
        limits = [(self.max_resources, 1, 20), (self.max_response_bytes, 10_000, 2_000_000),
                  (self.max_document_bytes, 1000, 200_000), (self.max_requests, 2, 100),
                  (self.page_items, 1, 15), (self.deadline_seconds, 10, 120),
                  (self.sync_interval_seconds, 300, 86400), (self.lookback_days, 1, 90),
                  (self.workspace_bytes, 1_000_000, 1_000_000_000)]
        if any(type(value) is not int or not minimum <= value <= maximum for value, minimum, maximum in limits):
            raise ValueError('Invalid source limits')
        from .credentials import CredentialCipher
        CredentialCipher(self.token_keys)

    def configured(self, provider: str) -> bool:
        if not self.enabled or provider not in PROVIDERS:
            return False
        if provider in {'gmail', 'drive'}:
            return bool(self.google_client_id and self.google_client_secret)
        if provider == 'slack':
            return bool(self.slack_client_id and self.slack_client_secret)
        if provider == 'notion':
            return bool(self.notion_client_id and self.notion_client_secret)
        # GitHub readiness additionally checks the existing App configuration.
        return True

    def callback(self, provider: str) -> str:
        if provider not in PROVIDERS:
            raise ValueError('Unsupported source')
        return f'{self.public_api_url.rstrip("/")}/integrations/sources/{provider}/callback'


def load_source_settings() -> SourceSettings:
    try:
        names = {'max_resources': 'SOURCE_MAX_RESOURCES', 'max_response_bytes': 'SOURCE_MAX_RESPONSE_BYTES',
                 'max_document_bytes': 'SOURCE_MAX_DOCUMENT_BYTES', 'max_requests': 'SOURCE_MAX_REQUESTS',
                 'page_items': 'SOURCE_PAGE_ITEMS', 'deadline_seconds': 'SOURCE_DEADLINE_SECONDS',
                 'sync_interval_seconds': 'SOURCE_SYNC_INTERVAL_SECONDS', 'lookback_days': 'SOURCE_LOOKBACK_DAYS',
                 'workspace_bytes': 'SOURCE_WORKSPACE_BYTES'}
        defaults = SourceSettings()
        configured = SourceSettings(
            enabled=os.getenv('SOURCES_ENABLED', 'false').lower() == 'true',
            public_api_url=os.getenv('SOURCE_PUBLIC_API_URL', ''), frontend_url=os.getenv('SOURCE_FRONTEND_URL', ''),
            token_keys=tuple(key.strip() for key in os.getenv('SOURCE_TOKEN_KEYS', '').split(',') if key.strip()),
            google_client_id=os.getenv('SOURCE_GOOGLE_CLIENT_ID', ''), google_client_secret=os.getenv('SOURCE_GOOGLE_CLIENT_SECRET', ''),
            slack_client_id=os.getenv('SOURCE_SLACK_CLIENT_ID', ''), slack_client_secret=os.getenv('SOURCE_SLACK_CLIENT_SECRET', ''),
            notion_client_id=os.getenv('SOURCE_NOTION_CLIENT_ID', ''), notion_client_secret=os.getenv('SOURCE_NOTION_CLIENT_SECRET', ''),
            **{name: int(os.getenv(env, str(getattr(defaults, name)))) for name, env in names.items()},
        )
        configured.validate()
        return configured
    except (ValueError, TypeError):
        raise ValueError('Invalid source configuration') from None
