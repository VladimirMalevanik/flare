"""Independent server-owned bounds. Defaults are local/test fixtures, not tuned production limits."""
from dataclasses import asdict, dataclass, fields
import os


@dataclass(frozen=True)
class ImportPolicy:
    compressed_bytes: int = 16_000_000
    expanded_bytes: int = 32_000_000
    entries: int = 2_000
    directory_bytes: int = 2_000_000
    manifest_bytes: int = 4_000_000
    file_bytes: int = 200_000
    path_bytes: int = 1_024
    segment_bytes: int = 255
    path_depth: int = 32
    expansion_ratio: int = 500
    csv_rows: int = 20_000
    csv_field_bytes: int = 100_000
    csv_row_bytes: int = 200_000
    chunks_file: int = 2_000
    chunks_package: int = 10_000
    chunk_bytes: int = 4_000
    upload_seconds: int = 120
    inspect_seconds: int = 30
    file_seconds: int = 30
    job_seconds: int = 300
    cpu_seconds: int = 120
    memory_bytes: int = 512_000_000
    scratch_bytes: int = 64_000_000
    staged_quota_bytes: int = 64_000_000
    source_quota_bytes: int = 128_000_000
    workspace_concurrency: int = 2
    global_concurrency: int = 2
    attempts: int = 3
    lease_seconds: int = 60
    backoff_seconds: int = 5
    staging_seconds: int = 3_600
    cleanup_seconds: int = 3_600
    report_page: int = 100

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise ValueError("Import policy fields must be positive integers")
        if self.attempts > 10 or self.report_page > 100 or self.chunk_bytes > self.file_bytes:
            raise ValueError("Invalid import policy bounds")

    @classmethod
    def from_environment(cls, *, production: bool = False):
        values = {}
        for field in fields(cls):
            key = f"FLARE_IMPORT_{field.name.upper()}"
            value = os.getenv(key)
            if production and value is None:
                raise ValueError(f"Production import requires explicit {key}")
            if value is not None:
                values[field.name] = int(value)
        return cls(**values)
