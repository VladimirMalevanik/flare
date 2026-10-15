"""Validation and response helpers for workspace campaign links."""

import re
from urllib.parse import urlencode, urlsplit

from app.models.campaign_links import CampaignLinkRecord, CampaignLinkRepository


DESTINATIONS = frozenset({"/", "/register", "/login"})
_UTM = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")


class InvalidCampaignLink(ValueError):
    pass


def normalize_label(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidCampaignLink("invalid_label")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 80 or any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise InvalidCampaignLink("invalid_label")
    return normalized


def normalize_utm(value: str | None, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise InvalidCampaignLink("invalid_utm")
    normalized = value.strip().lower()
    if optional and not normalized:
        return None
    if not _UTM.fullmatch(normalized):
        raise InvalidCampaignLink("invalid_utm")
    return normalized


def validate_destination(value: str) -> str:
    if not isinstance(value, str) or value not in DESTINATIONS:
        raise InvalidCampaignLink("invalid_destination")
    return value


def destination_url(destination) -> str:
    values = [
        ("utm_source", destination.utm_source),
        ("utm_medium", destination.utm_medium),
        ("utm_campaign", destination.utm_campaign),
    ]
    if destination.utm_content is not None:
        values.append(("utm_content", destination.utm_content))
    return f"{destination.destination_path}?{urlencode(values)}"


def public_origin(configured: str | None, fallback: str) -> str:
    candidate = configured or fallback
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise InvalidCampaignLink("invalid_public_origin")
    return f"{parsed.scheme}://{parsed.netloc}"


class CampaignLinkService:
    def __init__(self, repository: CampaignLinkRepository):
        self.repository = repository

    def create(self, *, label: str, destination_path: str, utm_source: str,
               utm_medium: str, utm_campaign: str,
               utm_content: str | None) -> CampaignLinkRecord:
        return self.repository.create(
            label=normalize_label(label),
            destination_path=validate_destination(destination_path),
            utm_source=normalize_utm(utm_source),
            utm_medium=normalize_utm(utm_medium),
            utm_campaign=normalize_utm(utm_campaign),
            utm_content=normalize_utm(utm_content, optional=True),
        )

    def list(self) -> list[CampaignLinkRecord]:
        return self.repository.list()

    def get(self, link_id):
        return self.repository.get(link_id)

    def rename(self, link_id, label: str):
        return self.repository.rename(link_id, normalize_label(label))

    def archive(self, link_id):
        return self.repository.archive(link_id)
