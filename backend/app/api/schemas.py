"""Validated HTTP contracts shared with the web client."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.tables import ItemRecord


NonBlankTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
NoteContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200_000),
]


class HealthResponse(BaseModel):
    status: str


class CreateItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["note"]
    title: NonBlankTitle | None = None
    content: NoteContent


class ExtractedFactResponse(BaseModel):
    id: str
    text: str


class ItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    type: Literal["note", "url", "file", "audio"]
    title: str
    content: str
    source_url: str | None = Field(default=None, serialization_alias="sourceUrl")
    file_name: str | None = Field(default=None, serialization_alias="fileName")
    file_size: int | None = Field(default=None, serialization_alias="fileSize")
    file_type: str | None = Field(default=None, serialization_alias="fileType")
    status: Literal["ready", "processing", "error"]
    created_at: datetime = Field(serialization_alias="createdAt")
    extracted_facts: list[ExtractedFactResponse] = Field(
        default_factory=list,
        serialization_alias="extractedFacts",
    )
    related_item_ids: list[str] = Field(
        default_factory=list,
        serialization_alias="relatedItemIds",
    )

    @classmethod
    def from_record(cls, record: ItemRecord) -> "ItemResponse":
        state_to_status = {
            "pending": "processing",
            "processing": "processing",
            "ready": "ready",
            "failed": "error",
        }
        metadata = record.metadata or {}
        facts = metadata.get("extractedFacts", [])
        related_ids = metadata.get("relatedItemIds", [])
        return cls(
            id=record.id,
            type=record.item_type,
            title=record.title,
            content=record.content,
            source_url=record.source_url,
            file_name=metadata.get("fileName"),
            file_size=metadata.get("fileSize"),
            file_type=metadata.get("fileType"),
            status=state_to_status[record.state],
            created_at=record.created_at,
            extracted_facts=facts if isinstance(facts, list) else [],
            related_item_ids=related_ids if isinstance(related_ids, list) else [],
        )
