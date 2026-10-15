"""Workspace campaign-link persistence and anonymous aggregate opens."""

from dataclasses import dataclass
from datetime import datetime
import logging
import re
import secrets
import threading
import time
from uuid import UUID, uuid4

import psycopg

from app.models.database import Database, WorkspaceIdentity


SLUG_PATTERN = re.compile(r"[A-Za-z0-9_-]{22,32}\Z")
_LOGGER = logging.getLogger(__name__)
_COUNT_WARNING_LOCK = threading.Lock()
_LAST_COUNT_WARNING = float("-inf")
_COUNT_WARNING_INTERVAL_SECONDS = 60.0


def _warn_count_failure() -> None:
    """Emit a bounded, payload-free signal while keeping redirects fail-open."""
    global _LAST_COUNT_WARNING
    now = time.monotonic()
    with _COUNT_WARNING_LOCK:
        if now - _LAST_COUNT_WARNING < _COUNT_WARNING_INTERVAL_SECONDS:
            return
        _LAST_COUNT_WARNING = now
    _LOGGER.warning("campaign_link_count_failed")


class CampaignLinkNotFound(Exception):
    pass


class CampaignLinkLimitReached(Exception):
    pass


@dataclass(frozen=True)
class CampaignLinkRecord:
    id: UUID
    workspace_id: UUID
    label: str
    slug: str
    destination_path: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str | None
    click_count: int
    created_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class CampaignLinkDestination:
    destination_path: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str | None


_COLUMNS = """id,workspace_id,label,slug,destination_path,utm_source,utm_medium,
              utm_campaign,utm_content,click_count,created_at,archived_at"""


class CampaignLinkRepository:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self.database = database
        self.identity = identity

    @staticmethod
    def new_slug() -> str:
        value = secrets.token_urlsafe(18)
        if not SLUG_PATTERN.fullmatch(value):
            raise RuntimeError("Secure slug generation failed")
        return value

    def create(
        self,
        *,
        label: str,
        destination_path: str,
        utm_source: str,
        utm_medium: str,
        utm_campaign: str,
        utm_content: str | None,
    ) -> CampaignLinkRecord:
        # A 144-bit random slug collision is not expected, but bounded retries
        # keep a synthetic collision from becoming an unrelated 503.
        for _attempt in range(3):
            slug = self.new_slug()
            try:
                with self.database.workspace_transaction(
                    self.identity,
                    write=True,
                    statement_timeout_ms=1_000,
                    lock_timeout_ms=500,
                ) as connection:
                    row = connection.execute(
                        f"""INSERT INTO public.campaign_links(
                               id,workspace_id,label,slug,destination_path,
                               utm_source,utm_medium,utm_campaign,utm_content)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING {_COLUMNS}""",
                        (
                            uuid4(), self.identity.workspace_id, label, slug,
                            destination_path, utm_source, utm_medium, utm_campaign,
                            utm_content,
                        ),
                    ).fetchone()
                return CampaignLinkRecord(**row)
            except psycopg.errors.UniqueViolation:
                continue
            except psycopg.errors.RaiseException as error:
                if error.diag.message_primary == "Campaign link limit reached":
                    raise CampaignLinkLimitReached from None
                raise
        raise RuntimeError("Secure slug allocation failed")

    def list(self) -> list[CampaignLinkRecord]:
        with self.database.workspace_transaction(
            self.identity, statement_timeout_ms=1_000,
        ) as connection:
            rows = connection.execute(
                f"""SELECT {_COLUMNS} FROM public.campaign_links
                    WHERE workspace_id=%s
                    -- Keep every active link visible while bounding archived
                    -- history returned to one browser request.
                    ORDER BY (archived_at IS NULL) DESC,created_at DESC,id DESC
                    LIMIT 100""",
                (self.identity.workspace_id,),
            ).fetchall()
        return [CampaignLinkRecord(**row) for row in rows]

    def get(self, link_id: UUID) -> CampaignLinkRecord:
        with self.database.workspace_transaction(
            self.identity, statement_timeout_ms=1_000,
        ) as connection:
            row = connection.execute(
                f"""SELECT {_COLUMNS} FROM public.campaign_links
                    WHERE workspace_id=%s AND id=%s""",
                (self.identity.workspace_id, link_id),
            ).fetchone()
        if row is None:
            raise CampaignLinkNotFound
        return CampaignLinkRecord(**row)

    def rename(self, link_id: UUID, label: str) -> CampaignLinkRecord:
        with self.database.workspace_transaction(
            self.identity,
            write=True,
            statement_timeout_ms=1_000,
            lock_timeout_ms=500,
        ) as connection:
            row = connection.execute(
                f"""UPDATE public.campaign_links SET label=%s
                    WHERE workspace_id=%s AND id=%s
                    RETURNING {_COLUMNS}""",
                (label, self.identity.workspace_id, link_id),
            ).fetchone()
        if row is None:
            raise CampaignLinkNotFound
        return CampaignLinkRecord(**row)

    def archive(self, link_id: UUID) -> CampaignLinkRecord:
        with self.database.workspace_transaction(
            self.identity,
            write=True,
            statement_timeout_ms=1_000,
            lock_timeout_ms=500,
        ) as connection:
            row = connection.execute(
                f"""UPDATE public.campaign_links
                    SET archived_at=coalesce(archived_at,clock_timestamp())
                    WHERE workspace_id=%s AND id=%s
                    RETURNING {_COLUMNS}""",
                (self.identity.workspace_id, link_id),
            ).fetchone()
        if row is None:
            raise CampaignLinkNotFound
        return CampaignLinkRecord(**row)

class CampaignLinkOpener:
    def __init__(self, database: Database):
        self.database = database

    def open(self, slug: str) -> CampaignLinkDestination | None:
        # Reject junk before acquiring a pool connection. The database repeats
        # the same constraint because this is a public write capability.
        if not SLUG_PATTERN.fullmatch(slug):
            return None
        with self.database.connection(timeout=1) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL statement_timeout='500ms'")
                row = connection.execute(
                    "SELECT * FROM public.campaign_link_resolve(%s)", (slug,),
                ).fetchone()
        if row is None:
            return None
        destination = CampaignLinkDestination(**row)
        # The destination was durably resolved first. Counter contention or a
        # transient telemetry failure must never break an already shared link.
        try:
            with self.database.connection(timeout=.5) as connection:
                with connection.transaction():
                    connection.execute("SET LOCAL statement_timeout='250ms'")
                    connection.execute("SET LOCAL lock_timeout='100ms'")
                    connection.execute(
                        "SELECT public.campaign_link_count(%s)", (slug,),
                    ).fetchone()
        except Exception:
            _warn_count_failure()
        return destination
