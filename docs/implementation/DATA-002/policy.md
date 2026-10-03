# Server-owned import policy

Every value below is a **local/test software default**, not a production recommendation, measured maximum, promised capacity or final product setting. Each control can be changed independently; no value is derived from the decoder benchmark. New sessions store a snapshot of the complete policy. Configuration is server-owned and is not accepted in client request bodies.

Production storage requires an explicitly configured server-owned policy. The standard environment loader requires every policy variable; alternatively, the application factory can receive an explicit policy object. The ordinary application can still run with ZIP capability disabled until OPS supplies an adapter. Local staging cannot be enabled in production.

| Control | Environment variable | Local/test default | Unit / enforcement |
| --- | --- | ---: | --- |
| `compressed_bytes` | `FLARE_IMPORT_COMPRESSED_BYTES` | 16,000,000 | bytes |
| `expanded_bytes` | `FLARE_IMPORT_EXPANDED_BYTES` | 32,000,000 | bytes |
| `entries` | `FLARE_IMPORT_ENTRIES` | 2,000 | count |
| `directory_bytes` | `FLARE_IMPORT_DIRECTORY_BYTES` | 2,000,000 | bytes |
| `manifest_bytes` | `FLARE_IMPORT_MANIFEST_BYTES` | 4,000,000 | bytes |
| `file_bytes` | `FLARE_IMPORT_FILE_BYTES` | 200,000 | bytes |
| `path_bytes` | `FLARE_IMPORT_PATH_BYTES` | 1,024 | bytes |
| `segment_bytes` | `FLARE_IMPORT_SEGMENT_BYTES` | 255 | bytes |
| `path_depth` | `FLARE_IMPORT_PATH_DEPTH` | 32 | path segments |
| `expansion_ratio` | `FLARE_IMPORT_EXPANSION_RATIO` | 500 | maximum expanded/compressed ratio per entry |
| `csv_rows` | `FLARE_IMPORT_CSV_ROWS` | 20,000 | count |
| `csv_field_bytes` | `FLARE_IMPORT_CSV_FIELD_BYTES` | 100,000 | bytes |
| `csv_row_bytes` | `FLARE_IMPORT_CSV_ROW_BYTES` | 200,000 | bytes |
| `chunks_file` | `FLARE_IMPORT_CHUNKS_FILE` | 2,000 | count |
| `chunks_package` | `FLARE_IMPORT_CHUNKS_PACKAGE` | 10,000 | count |
| `chunk_bytes` | `FLARE_IMPORT_CHUNK_BYTES` | 4,000 | UTF-8 bytes/chunk |
| `upload_seconds` | `FLARE_IMPORT_UPLOAD_SECONDS` | 120 | seconds |
| `inspect_seconds` | `FLARE_IMPORT_INSPECT_SECONDS` | 30 | seconds |
| `file_seconds` | `FLARE_IMPORT_FILE_SECONDS` | 30 | seconds |
| `job_seconds` | `FLARE_IMPORT_JOB_SECONDS` | 300 | seconds |
| `cpu_seconds` | `FLARE_IMPORT_CPU_SECONDS` | 120 | aggregate decoder CPU/job; individual child also constrained |
| `memory_bytes` | `FLARE_IMPORT_MEMORY_BYTES` | 512,000,000 | bytes |
| `scratch_bytes` | `FLARE_IMPORT_SCRATCH_BYTES` | 64,000,000 | ZIP scratch copy plus one child output |
| `staged_quota_bytes` | `FLARE_IMPORT_STAGED_QUOTA_BYTES` | 64,000,000 | undeleted object attempts plus unstarted upload reservations |
| `source_quota_bytes` | `FLARE_IMPORT_SOURCE_QUOTA_BYTES` | 128,000,000 | existing/staged source chunks plus unmaterialized parsed reservations |
| `workspace_concurrency` | `FLARE_IMPORT_WORKSPACE_CONCURRENCY` | 2 | active admitted packages/workspace |
| `global_concurrency` | `FLARE_IMPORT_GLOBAL_CONCURRENCY` | 2 | simultaneously leased package jobs; stored server policy also enforced by SQL |
| `attempts` | `FLARE_IMPORT_ATTEMPTS` | 3 | bounded processing attempts (maximum representable contract: 10) |
| `lease_seconds` | `FLARE_IMPORT_LEASE_SECONDS` | 60 | seconds |
| `backoff_seconds` | `FLARE_IMPORT_BACKOFF_SECONDS` | 5 | base delay, multiplied by bounded attempt count |
| `staging_seconds` | `FLARE_IMPORT_STAGING_SECONDS` | 3,600 | seconds |
| `cleanup_seconds` | `FLARE_IMPORT_CLEANUP_SECONDS` | 3,600 | overdue threshold; undeleted obligations remain retryable |
| `report_page` | `FLARE_IMPORT_REPORT_PAGE` | 100 | maximum report/receipt page entries (API hard ceiling: 100) |

All fields require positive integers. Attempts and report size have protocol ceilings; a chunk cannot exceed the individual file bound. ZIP64/multi-volume and compression other than Stored/Deflate are unsupported format capabilities of v1, independently of the configured byte bounds.

CPU, RAM and scratch use application/runtime controls where supported. macOS RAM supervision has sampling/kill latency; Linux uses an address-space limit. Neither proves a production resident-memory budget or storage operation deadline. OPS must verify container/OS limits and adapter I/O deadlines on the chosen infrastructure.

Staging/source accounting conservatively bounds ZIP work; it does not establish a universal workspace quota on existing independent capture/edit operations. The final gate rechecks actual source bytes. Expiry never drops a physical deletion obligation. Local retirement metadata is content-free and retained to fence late writers; its operational retention/inode budget belongs in the production adapter decision.
