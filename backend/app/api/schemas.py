"""Validated HTTP contracts shared with the web client."""

from datetime import datetime
from typing import Annotated, Any, Literal
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
SourceUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
]
FileName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
FileType = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]


class HealthResponse(BaseModel):
    status: str


class CreateItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["note", "url", "file", "audio"]
    title: NonBlankTitle | None = None
    content: NoteContent | None = None
    source_url: SourceUrl | None = Field(default=None, serialization_alias="sourceUrl", validation_alias="sourceUrl")
    file_name: FileName | None = Field(default=None, serialization_alias="fileName", validation_alias="fileName")
    file_size: int | None = Field(default=None, ge=0, serialization_alias="fileSize", validation_alias="fileSize")
    file_type: FileType | None = Field(default=None, serialization_alias="fileType", validation_alias="fileType")

    def effective_content(self) -> str:
        if self.content is not None:
            return self.content.strip()
        if self.type == "url" and self.source_url:
            return self.source_url.strip()
        if self.type == "file" and self.file_name:
            return f"File upload metadata only: {self.file_name}"
        if self.type == "audio":
            return "Audio memo"
        return ""


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


class CreateImportRequest(BaseModel):
    """JSON text-upload contract for the deliberately bounded import v1."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format: Literal["csv", "txt", "md"]
    file_name: str = Field(
        min_length=1,
        max_length=300,
        serialization_alias="fileName",
        validation_alias="fileName",
    )
    file_type: str | None = Field(
        default=None,
        max_length=120,
        serialization_alias="fileType",
        validation_alias="fileType",
    )
    file_size: int = Field(
        ge=0,
        strict=True,
        serialization_alias="fileSize",
        validation_alias="fileSize",
    )
    # Byte limits are enforced by ImportService after strict UTF-8 encoding;
    # character limits would incorrectly allow too many multi-byte characters.
    content: str = Field(min_length=1, max_length=200_000)


class ImportResponse(BaseModel):
    """One canonical import batch and its normal knowledge-item projection."""

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    format: Literal["csv", "txt", "md"]
    file_name: str = Field(serialization_alias="fileName")
    item: ItemResponse
    row_count: int | None = Field(serialization_alias="rowCount")
    chunk_count: int = Field(serialization_alias="chunkCount")
    analysis_jobs_queued: int = Field(serialization_alias="analysisJobsQueued")


class QueueSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pending: int
    processing: int
    completed: int
    failed: int
    due: int
    stale_processing: int = Field(serialization_alias="staleProcessing")
    oldest_pending_seconds: float | None = Field(serialization_alias="oldestPendingSeconds")
    oldest_processing_seconds: float | None = Field(serialization_alias="oldestProcessingSeconds")


class QueueHealthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    as_of: datetime = Field(serialization_alias="asOf")
    analysis: QueueSummary
    flares: QueueSummary
    alerts: list[str]


class QueueMaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dry_run: bool = Field(default=True, alias="dryRun")
    recover_stale: bool = Field(default=True, alias="recoverStale")
    max_rows: int = Field(default=2_000, ge=1, le=50_000, alias="maxRows")
    analysis_completed_retention_days: int = Field(
        default=30, ge=1, le=3650, alias="analysisCompletedRetentionDays"
    )
    analysis_failed_retention_days: int = Field(
        default=14, ge=1, le=3650, alias="analysisFailedRetentionDays"
    )
    flare_completed_retention_days: int = Field(
        default=30, ge=1, le=3650, alias="flareCompletedRetentionDays"
    )
    flare_failed_retention_days: int = Field(
        default=14, ge=1, le=3650, alias="flareFailedRetentionDays"
    )


class QueueBucketSummary(BaseModel):
    candidates: int
    deleted: int


class QueueMaintenanceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dry_run: bool = Field(serialization_alias="dryRun")
    applied: bool
    before: QueueHealthResponse
    after: QueueHealthResponse
    recovered_stale_analysis_jobs: int = Field(serialization_alias="recoveredStaleAnalysisJobs")
    recovered_stale_flare_runs: int = Field(serialization_alias="recoveredStaleFlareRuns")
    analysis_jobs: QueueBucketSummary = Field(serialization_alias="analysisJobs")
    flare_generation_runs: QueueBucketSummary = Field(serialization_alias="flareGenerationRuns")


class AnalyticsEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "capture_started",
        "capture_submitted",
        "capture_file_attached",
        "capture_voice_started",
        "capture_voice_stopped",
        "item_created",
        "item_deleted",
        "item_viewed",
        "flare_viewed",
        "queue_health_requested",
        "queue_maintenance_run",
        "import_started",
        "import_completed",
        "import_failed",
    ] = Field(serialization_alias="eventType", validation_alias="eventType")
    target_type: str | None = Field(
        default=None,
        max_length=80,
        serialization_alias="targetType",
        validation_alias="targetType",
    )
    target_id: str | None = Field(
        default=None,
        max_length=80,
        serialization_alias="targetId",
        validation_alias="targetId",
    )
    metadata: dict[str, Any] | None = None


class AnalyticsEventSummaryItem(BaseModel):
    event_type: str
    count: int


class AnalyticsSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    window_hours: int
    since: str
    until: str
    events: list[AnalyticsEventSummaryItem]
