"""Bounded workspace export to a portable Markdown and JSON ZIP archive."""

from __future__ import annotations

from datetime import datetime, timezone
from io import TextIOWrapper
import json
import re
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO, Iterator
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from app.models.database import Database, WorkspaceIdentity
from app.models.flares import SELECT_FLARES
from app.models.tables import ItemRepository


PAGE_SIZE = 100
SPOOL_LIMIT_BYTES = 8 * 1024 * 1024
SAFE_METADATA_KEYS = (
    "sourceType",
    "sourceUrl",
    "fileName",
    "fileSize",
    "fileType",
    "originImportBatchId",
)


class WorkspaceExport:
    def __init__(self, file: BinaryIO, filename: str):
        self.file = file
        self.filename = filename

    def chunks(self, size: int = 64 * 1024) -> Iterator[bytes]:
        try:
            while chunk := self.file.read(size):
                yield chunk
        finally:
            self.file.close()


class WorkspaceExportService:
    def __init__(
        self,
        database: Database,
        identity: WorkspaceIdentity,
        *,
        clock=None,
    ):
        self._database = database
        self._identity = identity
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def build(self) -> WorkspaceExport:
        now = self._clock()
        file = SpooledTemporaryFile(max_size=SPOOL_LIMIT_BYTES, mode="w+b")
        try:
            with self._database.workspace_transaction(self._identity) as connection:
                workspace = connection.execute(
                    "SELECT id,name,created_at FROM public.workspaces WHERE id=%s",
                    (self._identity.workspace_id,),
                ).fetchone()
                if workspace is None:
                    raise ValueError("workspace_unavailable")
                workspace_data = {
                    "id": str(workspace["id"]),
                    "name": workspace["name"],
                    "createdAt": self._iso(workspace["created_at"]),
                    "exportedAt": self._iso(now),
                }
                with ZipFile(file, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                    archive.writestr("README.md", self._readme(workspace_data))
                    archive.writestr(
                        "workspace.json",
                        json.dumps(workspace_data, ensure_ascii=False, indent=2) + "\n",
                    )
                    for item in self._items(connection):
                        archive.writestr(
                            f"notes/{item['id']}-{self._slug(item['title'])}.md",
                            self._item_markdown(item),
                        )
                    for flare in self._flares(connection):
                        archive.writestr(
                            f"flares/{flare['id']}-{self._slug(flare['title'])}.md",
                            self._flare_markdown(flare),
                        )
                    with archive.open("raw/export.json", "w") as raw:
                        text = TextIOWrapper(raw, encoding="utf-8", write_through=True)
                        text.write('{\n  "workspace": ')
                        json.dump(workspace_data, text, ensure_ascii=False)
                        text.write(',\n  "notes": [')
                        self._write_json_rows(text, self._items(connection))
                        text.write('],\n  "flares": [')
                        self._write_json_rows(text, self._flares(connection))
                        text.write("]\n}\n")
                        text.detach()
            file.seek(0)
            return WorkspaceExport(file, f"flare-export-{now.date().isoformat()}.zip")
        except Exception:
            file.close()
            raise

    def _items(self, connection) -> Iterator[dict[str, Any]]:
        after: UUID | None = None
        while True:
            suffix = " AND d.id>%s" if after is not None else ""
            parameters: tuple[object, ...] = ((after, PAGE_SIZE) if after is not None else (PAGE_SIZE,))
            rows = connection.execute(
                ItemRepository._SELECT_ITEM
                + " WHERE d.deleted_at IS NULL AND v.state='ready'"
                + suffix
                + " ORDER BY d.id LIMIT %s",
                parameters,
            ).fetchall()
            if not rows:
                return
            for row in rows:
                metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
                yield {
                    "id": str(row["id"]),
                    "type": row["item_type"],
                    "title": row["title"],
                    "content": row["content"],
                    "sourceUrl": row["source_url"],
                    "metadata": {
                        key: metadata[key] for key in SAFE_METADATA_KEYS if key in metadata
                    },
                    "createdAt": self._iso(row["created_at"]),
                    "updatedAt": self._iso(row["updated_at"]),
                    "currentVersionId": str(row["current_version_id"]),
                    "versionNumber": row["version_number"],
                }
            after = rows[-1]["id"]
            if len(rows) < PAGE_SIZE:
                return

    def _flares(self, connection) -> Iterator[dict[str, Any]]:
        after: UUID | None = None
        while True:
            suffix = " AND i.id>%s" if after is not None else ""
            parameters: tuple[object, ...] = ((after, PAGE_SIZE) if after is not None else (PAGE_SIZE,))
            rows = connection.execute(
                SELECT_FLARES + suffix + " ORDER BY i.id LIMIT %s",
                parameters,
            ).fetchall()
            if not rows:
                return
            for row in rows:
                yield {
                    "id": str(row["id"]),
                    "type": row["type"],
                    "title": row["title"],
                    "statement": row["statement"],
                    "action": row["action"],
                    "reason": row["reason"],
                    "createdAt": self._iso(row["created_at"]),
                    "evidence": [
                        {
                            **entry,
                            "itemId": str(entry["itemId"]),
                        }
                        for entry in row["evidence"]
                    ],
                }
            after = rows[-1]["id"]
            if len(rows) < PAGE_SIZE:
                return

    @staticmethod
    def _write_json_rows(stream: TextIOWrapper, rows: Iterator[dict[str, Any]]) -> None:
        separator = ""
        for row in rows:
            stream.write(separator)
            json.dump(row, stream, ensure_ascii=False)
            separator = ","

    @staticmethod
    def _readme(workspace: dict[str, str]) -> str:
        return (
            "# Flare workspace export\n\n"
            f"Workspace: {WorkspaceExportService._inline(workspace['name'])}\n\n"
            "This archive contains readable Markdown and machine-readable JSON.\n\n"
            "- `workspace.json` contains workspace identity and export timestamps.\n"
            "- `notes/` contains current Notes and supported imported text.\n"
            "- `flares/` contains current Flares and evidence references.\n"
            "- `raw/export.json` contains the complete portable export.\n"
        )

    @staticmethod
    def _item_markdown(item: dict[str, Any]) -> str:
        lines = [
            f"# {WorkspaceExportService._inline(item['title'])}",
            "",
            f"- ID: `{item['id']}`",
            f"- Type: `{item['type']}`",
            f"- Created: `{item['createdAt']}`",
            f"- Updated: `{item['updatedAt']}`",
            f"- Current version: `{item['currentVersionId']}`",
            f"- Version number: `{item['versionNumber']}`",
        ]
        if item["sourceUrl"]:
            lines.append(f"- Source URL: {item['sourceUrl']}")
        if item["metadata"]:
            lines.extend(("", "## Source metadata", "", "```json", json.dumps(
                item["metadata"], ensure_ascii=False, indent=2
            ), "```"))
        lines.extend(("", "## Content", "", item["content"], ""))
        return "\n".join(lines)

    @staticmethod
    def _flare_markdown(flare: dict[str, Any]) -> str:
        lines = [
            f"# {WorkspaceExportService._inline(flare['title'])}",
            "",
            f"- ID: `{flare['id']}`",
            f"- Type: `{flare['type']}`",
            f"- Created: `{flare['createdAt']}`",
            "",
            "## Statement",
            "",
            flare["statement"],
        ]
        if flare["action"]:
            lines.extend(("", "## Action", "", flare["action"]))
        lines.extend(("", "## Reason", "", flare["reason"], "", "## Evidence", ""))
        for evidence in flare["evidence"]:
            lines.extend((
                f"### {WorkspaceExportService._inline(evidence['sourceTitle'])}",
                "",
                f"- Item ID: `{evidence['itemId']}`",
                f"- Source type: `{evidence['sourceType']}`",
                "",
                f"> {evidence['excerpt']}",
                "",
            ))
        return "\n".join(lines)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]
        return slug or "untitled"

    @staticmethod
    def _inline(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
