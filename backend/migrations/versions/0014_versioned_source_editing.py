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
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

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

        UPDATE public.documents
           SET metadata = (metadata - 'importBatchId') || jsonb_build_object(
               'originImportBatchId', metadata->>'importBatchId'
           )
         WHERE metadata ? 'importBatchId';

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
