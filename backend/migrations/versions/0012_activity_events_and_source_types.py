"""Add operational activity events and enable audio documents in production schema."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public'
               AND t.relname = 'documents'
               AND c.contype = 'c'
               AND pg_get_constraintdef(c.oid) LIKE '%source_type%'
             LIMIT 1;
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE public.documents DROP CONSTRAINT %I', constraint_name);
            END IF;

            ALTER TABLE public.documents
                ADD CONSTRAINT documents_source_type_check
                    CHECK (source_type IN ('file', 'url', 'note', 'audio'));
        END;
        $$;

        CREATE TABLE public.activity_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            actor_id text NOT NULL CHECK (length(btrim(actor_id)) > 0),
            event_type text NOT NULL CHECK (
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
                    'queue_maintenance_run'
                )
            ),
            target_type text,
            target_id uuid,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (jsonb_typeof(metadata) = 'object')
        );
        ALTER TABLE public.activity_events ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.activity_events FORCE ROW LEVEL SECURITY;
        CREATE POLICY workspace_isolation ON public.activity_events
            USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid);
        CREATE POLICY activity_event_member_access ON public.activity_events
            AS RESTRICTIVE TO flare_app
            USING (EXISTS (
                SELECT 1 FROM public.workspace_members m
                 WHERE m.workspace_id = activity_events.workspace_id
                   AND m.user_id = nullif(current_setting('app.user_id', true), '')
            ));
        CREATE POLICY activity_event_actor_insert ON public.activity_events
            AS RESTRICTIVE FOR INSERT TO flare_app
            WITH CHECK (
                actor_id = nullif(current_setting('app.user_id', true), '')
                AND EXISTS (
                    SELECT 1 FROM public.workspace_members m
                     WHERE m.workspace_id = activity_events.workspace_id
                       AND m.user_id = nullif(current_setting('app.user_id', true), '')
                )
            );
        CREATE INDEX activity_events_workspace_created_idx
            ON public.activity_events(workspace_id, created_at DESC);
        CREATE INDEX activity_events_type_created_idx
            ON public.activity_events(workspace_id, event_type, created_at DESC);
        REVOKE ALL ON public.activity_events FROM PUBLIC;
        GRANT SELECT, INSERT ON public.activity_events TO flare_app;
        """
    )


def downgrade():
    raise RuntimeError("Operation not safely reversible; restore from backup or a newer migration plan.")
