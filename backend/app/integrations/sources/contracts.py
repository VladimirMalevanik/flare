"""Small provider-neutral records; never include credentials in public results."""
from dataclasses import dataclass, field
from typing import Any


class SourceProviderError(Exception):
    def __init__(self, code: str, *, retry_after: int | None = None, reconnect: bool = False):
        # Provider bodies/URLs/tokens must never become an exception message.
        super().__init__(code)
        self.code, self.retry_after, self.reconnect = code, retry_after, reconnect


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    kind: str

    def public(self) -> dict:
        return {'id': self.id, 'name': self.name, 'kind': self.kind}


@dataclass(frozen=True)
class ResourcePage:
    resources: tuple[Resource, ...]
    cursor: str | None = None


@dataclass(frozen=True)
class SourceDocument:
    external_id: str
    title: str
    content: str = field(repr=False)
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentPage:
    documents: tuple[SourceDocument, ...]
    cursor: dict | None = None
    skipped: int = 0
    # A provider can require a pause even after a successful page (Slack).
    delay_seconds: int = 0
