"""Add edit timestamps and exact import-to-version provenance."""

from alembic import op


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        ALTER TABLE public.documents
            ADD COLUMN updated_at timestamptz;
        -- Managed deployments run migrations as the table owner. FORCE RLS
        -- would otherwise hide every legacy row during this backfill.
        ALTER TABLE public.documents NO FORCE ROW LEVEL SECURITY;
        -- Preserve the real legacy recency order.  A DEFAULT added with the
        -- column would stamp every pre-migration row with the same instant.
        UPDATE public.documents SET updated_at = created_at;
        ALTER TABLE public.documents
            ALTER COLUMN updated_at SET DEFAULT now(),
            ALTER COLUMN updated_at SET NOT NULL;
        CREATE INDEX documents_workspace_updated_active_idx
            ON public.documents(workspace_id, updated_at DESC, id DESC)
            WHERE deleted_at IS NULL;

        -- A chunk is immutable, but citations also expose its human label and
        -- source URL.  Keep those fields (and display metadata used by import
        -- history) on the same immutable version boundary so a later edit
        -- cannot relabel evidence that an analysis already pinned.
        ALTER TABLE public.document_versions NO FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.import_batches NO FORCE ROW LEVEL SECURITY;
        UPDATE public.documents
           SET metadata = (metadata - 'importBatchId') || jsonb_build_object(
               'originImportBatchId', metadata->>'importBatchId'
           )
         WHERE metadata ? 'importBatchId';
        ALTER TABLE public.document_versions
            ADD COLUMN snapshot_title text,
            ADD COLUMN snapshot_source_url text,
            ADD COLUMN snapshot_metadata jsonb;

        -- Application code supplies every snapshot explicitly.  This fallback
        -- keeps migration checks and trusted legacy/admin ingestion paths safe:
        -- when the new columns are wholly absent, freeze the parent projection
        -- at INSERT time.  The invoker still has to see that parent through RLS.
        CREATE FUNCTION public.set_document_version_snapshot() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE
            parent_title text;
            parent_source_url text;
            parent_metadata jsonb;
            legacy_snapshot_missing boolean;
        BEGIN
            legacy_snapshot_missing :=
                NEW.snapshot_title IS NULL
                AND NEW.snapshot_source_url IS NULL
                AND NEW.snapshot_metadata IS NULL;
            IF NEW.snapshot_title IS NULL OR NEW.snapshot_metadata IS NULL THEN
                SELECT d.title, d.source_url, d.metadata
                  INTO parent_title, parent_source_url, parent_metadata
                  FROM public.documents d
                 WHERE (d.workspace_id, d.id) =
                       (NEW.workspace_id, NEW.document_id);
                NEW.snapshot_title := COALESCE(NEW.snapshot_title, parent_title);
                NEW.snapshot_metadata := COALESCE(NEW.snapshot_metadata, parent_metadata);
                IF legacy_snapshot_missing THEN
                    NEW.snapshot_source_url := parent_source_url;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER document_versions_snapshot
            BEFORE INSERT ON public.document_versions
            FOR EACH ROW EXECUTE FUNCTION public.set_document_version_snapshot();

        ALTER TABLE public.document_versions
            DISABLE TRIGGER document_versions_immutable;
        UPDATE public.document_versions v
           SET snapshot_title = d.title,
               snapshot_source_url = d.source_url,
               snapshot_metadata = d.metadata
          FROM public.documents d
         WHERE (d.workspace_id, d.id) = (v.workspace_id, v.document_id);
        ALTER TABLE public.document_versions
            ENABLE TRIGGER document_versions_immutable;
        ALTER TABLE public.document_versions
            ALTER COLUMN snapshot_title SET NOT NULL,
            ALTER COLUMN snapshot_metadata SET NOT NULL,
            ADD CONSTRAINT document_versions_snapshot_title_check
                CHECK (length(btrim(snapshot_title)) > 0),
            ADD CONSTRAINT document_versions_snapshot_metadata_check
                CHECK (jsonb_typeof(snapshot_metadata) = 'object');

        CREATE FUNCTION public.set_document_updated_at() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER documents_updated_at
            BEFORE UPDATE ON public.documents
            FOR EACH ROW EXECUTE FUNCTION public.set_document_updated_at();

        ALTER TABLE public.import_batches
            ADD COLUMN document_version_id uuid,
            ADD COLUMN superseded_at timestamptz;

        -- The 0013 transition guard intentionally rejects every completed-row
        -- update. Disable it only inside this migration transaction while the
        -- exact historical version link is backfilled.
        DROP TRIGGER import_batches_immutable ON public.import_batches;

        UPDATE public.import_batches b
           SET document_version_id = d.current_version_id
          FROM public.documents d
         WHERE b.status = 'completed'
           AND (d.workspace_id, d.id) = (b.workspace_id, b.document_id);

        ALTER TABLE public.import_batches
            ADD CONSTRAINT import_batches_document_version_fk
            FOREIGN KEY (workspace_id, document_id, document_version_id)
            REFERENCES public.document_versions(workspace_id, document_id, id);

        ALTER TABLE public.import_batches
            DROP CONSTRAINT import_batches_workspace_id_format_file_hash_key;
        CREATE UNIQUE INDEX import_batches_active_hash_unique
            ON public.import_batches(workspace_id, format, file_hash)
            WHERE superseded_at IS NULL;

        ALTER TABLE public.import_batches
            ADD CONSTRAINT import_batches_lifecycle_check CHECK (
                (status = 'processing' AND document_id IS NULL
                 AND document_version_id IS NULL AND row_count IS NULL
                 AND chunk_count = 0 AND analysis_jobs_queued = 0
                 AND completed_at IS NULL AND superseded_at IS NULL)
                OR
                (status = 'completed' AND document_id IS NOT NULL
                 AND document_version_id IS NOT NULL AND chunk_count > 0
                 AND completed_at IS NOT NULL)
            );

        CREATE OR REPLACE FUNCTION public.guard_import_batch_update() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            IF NEW.id <> OLD.id
                OR NEW.workspace_id <> OLD.workspace_id
                OR NEW.requested_by_user_id <> OLD.requested_by_user_id
                OR NEW.format <> OLD.format
                OR NEW.file_name <> OLD.file_name
                OR NEW.file_type IS DISTINCT FROM OLD.file_type
                OR NEW.file_size <> OLD.file_size
                OR NEW.file_hash <> OLD.file_hash
                OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'Import batch identity is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.status = 'processing' THEN
                IF NEW.status <> 'completed' OR NEW.superseded_at IS NOT NULL THEN
                    RAISE EXCEPTION 'Invalid import batch state transition' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status = 'completed'
                AND OLD.superseded_at IS NULL
                AND NEW.superseded_at IS NOT NULL
                AND NEW.status = OLD.status
                AND NEW.document_id = OLD.document_id
                AND NEW.document_version_id = OLD.document_version_id
                AND NEW.row_count IS NOT DISTINCT FROM OLD.row_count
                AND NEW.chunk_count = OLD.chunk_count
                AND NEW.analysis_jobs_queued = OLD.analysis_jobs_queued
                AND NEW.completed_at = OLD.completed_at THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid import batch state transition' USING ERRCODE = '23514';
        END;
        $$;
        CREATE TRIGGER import_batches_immutable
            BEFORE UPDATE ON public.import_batches
            FOR EACH ROW EXECUTE FUNCTION public.guard_import_batch_update();

        ALTER TABLE public.document_versions FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.documents FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.import_batches FORCE ROW LEVEL SECURITY;

        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public'
               AND t.relname = 'activity_events'
               AND c.contype = 'c'
               AND pg_get_constraintdef(c.oid) LIKE '%event_type%'
             LIMIT 1;
            IF constraint_name IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE public.activity_events DROP CONSTRAINT %I',
                    constraint_name
                );
            END IF;
            ALTER TABLE public.activity_events
                ADD CONSTRAINT activity_events_event_type_check CHECK (
                    event_type IN (
                        'capture_started',
                        'capture_submitted',
                        'capture_file_attached',
                        'capture_voice_started',
                        'capture_voice_stopped',
                        'item_created',
                        'item_updated',
                        'source_replaced',
                        'item_deleted',
                        'item_viewed',
                        'flare_viewed',
                        'queue_health_requested',
                        'queue_maintenance_run',
                        'import_started',
                        'import_completed',
                        'import_failed'
                    )
                );
        END;
        $$;
        """
    )


def downgrade():
    raise RuntimeError(
        "Versioned source edits retain customer history; restore from backup instead."
    )
