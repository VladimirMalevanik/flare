-- Initial MVP schema. Run once through Alembic as the migration administrator.
-- The API must verify workspace membership before setting the transaction-local
-- app.workspace_id. This setting is trusted server context, not authentication.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.workspace_members (
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    user_id text NOT NULL CHECK (length(btrim(user_id)) > 0),
    role text NOT NULL DEFAULT 'editor' CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX workspace_members_user_idx ON public.workspace_members(user_id);

CREATE TABLE public.documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    title text NOT NULL CHECK (length(btrim(title)) > 0),
    source_type text NOT NULL CHECK (source_type IN ('file', 'url', 'note')),
    source_url text,
    current_version_id uuid,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id)
);

CREATE TABLE public.document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    document_id uuid NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    storage_key text,
    parser_version text NOT NULL CHECK (length(btrim(parser_version)) > 0),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'processing', 'ready', 'failed')),
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, document_id, id),
    UNIQUE (document_id, version_number),
    FOREIGN KEY (workspace_id, document_id)
        REFERENCES public.documents(workspace_id, id) ON DELETE CASCADE
);

ALTER TABLE public.documents ADD CONSTRAINT documents_current_version_fk
    FOREIGN KEY (workspace_id, id, current_version_id)
    REFERENCES public.document_versions(workspace_id, document_id, id);

CREATE TABLE public.chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    content text NOT NULL CHECK (length(btrim(content)) > 0),
    locator jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(locator) = 'object'),
    embedding vector(1536),
    embedding_model text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id),
    UNIQUE (document_version_id, ordinal),
    FOREIGN KEY (workspace_id, document_version_id)
        REFERENCES public.document_versions(workspace_id, id) ON DELETE CASCADE,
    CHECK (embedding IS NULL OR
        (embedding_model IS NOT NULL AND length(btrim(embedding_model)) > 0))
);

CREATE TABLE public.insights (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    body text NOT NULL CHECK (length(btrim(body)) > 0),
    model text NOT NULL CHECK (length(btrim(model)) > 0),
    prompt_version text NOT NULL CHECK (length(btrim(prompt_version)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, id)
);

CREATE TABLE public.insight_sources (
    workspace_id uuid NOT NULL,
    insight_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    quote text,
    PRIMARY KEY (workspace_id, insight_id, chunk_id),
    FOREIGN KEY (workspace_id, insight_id)
        REFERENCES public.insights(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, chunk_id)
        REFERENCES public.chunks(workspace_id, id)
);
CREATE INDEX insight_sources_chunk_idx
    ON public.insight_sources(workspace_id, chunk_id);

-- Published snapshots are retained for citations. MVP deletion is a soft delete
-- on documents. A later retention/purge workflow must explicitly handle these
-- guards and citations; ordinary application writes cannot destroy snapshots.
CREATE FUNCTION public.guard_ready_version() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF OLD.state = 'ready' THEN
        RAISE EXCEPTION 'Ready document versions are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER document_versions_immutable
    BEFORE UPDATE OR DELETE ON public.document_versions
    FOR EACH ROW EXECUTE FUNCTION public.guard_ready_version();

CREATE FUNCTION public.guard_ready_chunks() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    parent_state text;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        -- Serialize ingestion against publication of the parent snapshot.
        SELECT state INTO parent_state FROM public.document_versions
            WHERE workspace_id = OLD.workspace_id AND id = OLD.document_version_id
            FOR UPDATE;
        IF parent_state = 'ready' THEN
            RAISE EXCEPTION 'Chunks of ready document versions are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT state INTO parent_state FROM public.document_versions
            WHERE workspace_id = NEW.workspace_id AND id = NEW.document_version_id
            FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Document version is unavailable in this workspace'
                USING ERRCODE = '23503';
        END IF;
        IF parent_state = 'ready' THEN
            RAISE EXCEPTION 'Chunks of ready document versions are immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER chunks_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON public.chunks
    FOR EACH ROW EXECUTE FUNCTION public.guard_ready_chunks();

CREATE FUNCTION public.guard_current_version() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    parent_state text;
BEGIN
    IF NEW.current_version_id IS NOT NULL THEN
        SELECT state INTO parent_state FROM public.document_versions
            WHERE workspace_id = NEW.workspace_id
                AND document_id = NEW.id AND id = NEW.current_version_id
            FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Current version must belong to this document and workspace'
                USING ERRCODE = '23503';
        END IF;
        IF parent_state <> 'ready' THEN
            RAISE EXCEPTION 'Current version must be ready' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER documents_current_version_ready
    BEFORE INSERT OR UPDATE OF workspace_id, id, current_version_id ON public.documents
    FOR EACH ROW EXECUTE FUNCTION public.guard_current_version();

-- A single workspace is selected by the trusted backend inside each transaction.
-- Missing/empty context denies access. FORCE also subjects table owners to RLS;
-- superusers and BYPASSRLS roles still bypass it and must not run application SQL.
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON public.workspaces
    USING (id = nullif(current_setting('app.workspace_id', true), '')::uuid)
    WITH CHECK (id = nullif(current_setting('app.workspace_id', true), '')::uuid);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'workspace_members', 'documents', 'document_versions', 'chunks',
        'insights', 'insight_sources'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY workspace_isolation ON public.%I '
            'USING (workspace_id = nullif(current_setting(''app.workspace_id'', true), '''')::uuid) '
            'WITH CHECK (workspace_id = nullif(current_setting(''app.workspace_id'', true), '''')::uuid)',
            table_name
        );
    END LOOP;
END;
$$;
