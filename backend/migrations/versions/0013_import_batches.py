"""Track bounded text imports and preserve their tenant boundary."""

from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        CREATE TABLE public.import_batches (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            requested_by_user_id text NOT NULL REFERENCES public.auth_users(id),
            format text NOT NULL CHECK (format IN ('csv', 'txt', 'md')),
            file_name text NOT NULL CHECK (length(btrim(file_name)) BETWEEN 1 AND 300),
            file_type text CHECK (file_type IS NULL OR length(btrim(file_type)) BETWEEN 1 AND 120),
            file_size integer NOT NULL CHECK (file_size BETWEEN 1 AND 200000),
            file_hash text NOT NULL CHECK (file_hash ~ '^[0-9a-f]{64}$'),
            status text NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'completed')),
            document_id uuid,
            row_count integer CHECK (row_count IS NULL OR row_count >= 0),
            chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
            analysis_jobs_queued integer NOT NULL DEFAULT 0 CHECK (analysis_jobs_queued >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            UNIQUE (workspace_id, id),
            UNIQUE (workspace_id, format, file_hash),
            FOREIGN KEY (workspace_id, document_id)
                REFERENCES public.documents(workspace_id, id),
            CHECK (
                (status = 'processing' AND document_id IS NULL
                 AND row_count IS NULL AND chunk_count = 0
                 AND analysis_jobs_queued = 0 AND completed_at IS NULL)
                OR
                (status = 'completed' AND document_id IS NOT NULL
                 AND chunk_count > 0 AND completed_at IS NOT NULL)
            )
        );
        CREATE INDEX import_batches_workspace_created_idx
            ON public.import_batches(workspace_id, created_at DESC, id DESC);

        ALTER TABLE public.import_batches ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.import_batches FORCE ROW LEVEL SECURITY;
        CREATE POLICY workspace_isolation ON public.import_batches
            USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid);
        CREATE POLICY import_batch_member_access ON public.import_batches
            AS RESTRICTIVE TO flare_app
            USING (EXISTS (
                SELECT 1 FROM public.workspace_members m
                 WHERE m.workspace_id = import_batches.workspace_id
                   AND m.user_id = nullif(current_setting('app.user_id', true), '')
            ));
        CREATE POLICY import_batch_writer_insert ON public.import_batches
            AS RESTRICTIVE FOR INSERT TO flare_app
            WITH CHECK (
                requested_by_user_id = nullif(current_setting('app.user_id', true), '')
                AND EXISTS (
                    SELECT 1 FROM public.workspace_members m
                     WHERE m.workspace_id = import_batches.workspace_id
                       AND m.user_id = nullif(current_setting('app.user_id', true), '')
                       AND m.role IN ('owner', 'editor')
                )
            );
        CREATE POLICY import_batch_writer_update ON public.import_batches
            AS RESTRICTIVE FOR UPDATE TO flare_app
            USING (EXISTS (
                SELECT 1 FROM public.workspace_members m
                 WHERE m.workspace_id = import_batches.workspace_id
                   AND m.user_id = nullif(current_setting('app.user_id', true), '')
                   AND m.role IN ('owner', 'editor')
            ))
            WITH CHECK (EXISTS (
                SELECT 1 FROM public.workspace_members m
                 WHERE m.workspace_id = import_batches.workspace_id
                   AND m.user_id = nullif(current_setting('app.user_id', true), '')
                   AND m.role IN ('owner', 'editor')
            ));
        REVOKE ALL ON public.import_batches FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON public.import_batches TO flare_app;

        CREATE FUNCTION public.guard_import_batch_update() RETURNS trigger
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
            IF OLD.status <> 'processing' OR NEW.status <> 'completed' THEN
                RAISE EXCEPTION 'Invalid import batch state transition' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER import_batches_immutable
            BEFORE UPDATE ON public.import_batches
            FOR EACH ROW EXECUTE FUNCTION public.guard_import_batch_update();

        -- Imported whitespace is still source text.  The original schema
        -- required btrim(content), which could not faithfully preserve a
        -- separator-only chunk at an analysis boundary.
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public'
               AND t.relname = 'chunks'
               AND c.contype = 'c'
               AND pg_get_constraintdef(c.oid) LIKE '%btrim(content)%'
             LIMIT 1;
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE public.chunks DROP CONSTRAINT %I', constraint_name);
            END IF;
            ALTER TABLE public.chunks
                ADD CONSTRAINT chunks_content_nonempty_check CHECK (length(content) > 0);
        END;
        $$;

        -- Keep import lifecycle telemetry in the constrained event vocabulary.
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
                EXECUTE format('ALTER TABLE public.activity_events DROP CONSTRAINT %I', constraint_name);
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
    raise RuntimeError("Import batches retain customer source data; restore from backup instead.")
