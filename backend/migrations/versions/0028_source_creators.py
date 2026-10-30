"""Trusted source authors and fresh bindings after a disconnected owner handoff."""
import os

from alembic import op
from sqlalchemy import text

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def patch(signature, replacements):
    # Patch the installed definition, retaining later Team gates, ownership,
    # search_path and ACLs. Released SQL snapshots must remain immutable.
    definition = op.get_bind().execute(
        text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
        {"signature": "public." + signature},
    ).scalar_one()
    for original, replacement in replacements:
        if not definition or definition.count(original) != 1:
            raise RuntimeError("Source authors require the reviewed function contract: " + signature)
        definition = definition.replace(original, replacement)
    op.execute(definition)


def upgrade():
    owner = "flare_owner" if os.getenv("FLARE_DATABASE_PROVIDER") == "yandex" else "flare_job_executor"
    op.execute(f"GRANT SELECT(name) ON public.auth_users TO {owner}")
    op.execute("""
        ALTER TABLE public.source_connections ADD COLUMN retired_at timestamptz,
            ADD CONSTRAINT source_retired_disabled CHECK(retired_at IS NULL OR
                (NOT enabled AND status='disabled' AND credential_blob IS NULL AND cursor_blob IS NULL));
        CREATE UNIQUE INDEX source_current_provider ON public.source_connections(workspace_id,provider)
            WHERE retired_at IS NULL;
        ALTER TABLE public.source_connections DROP CONSTRAINT source_connections_workspace_id_provider_key;
    """)
    patch("import_worker_step(uuid,uuid,bigint,text,jsonb)", [
        ("used bigint; title text;", "used bigint; title text; actor_name text;"),
        ("PERFORM id FROM public.auth_users WHERE id=p.requested_by_user_id AND NOT disabled FOR SHARE;",
         "SELECT name INTO actor_name FROM public.auth_users WHERE id=p.requested_by_user_id AND NOT disabled FOR SHARE;"),
        ("'fileHash',e.file_hash);", "'fileHash',e.file_hash,'createdBy',p.requested_by_user_id,'createdByName',actor_name);"),
    ])
    patch("source_api(text,uuid,jsonb)", [
        ("BEGIN\n PERFORM id FROM public.auth_users", """BEGIN
 -- Read-only provenance must also work for viewers and expired Team projects.
 -- No row locks here: item edits already hold a document lock.
 IF p_action='creators' THEN
  IF NOT EXISTS(SELECT 1 FROM public.auth_users a JOIN public.workspace_members m ON m.user_id=a.id
    WHERE a.id=u AND NOT a.disabled AND m.workspace_id=w) THEN RETURN jsonb_build_object('error','forbidden'); END IF;
  IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR octet_length(p_payload::text)>100000
    OR jsonb_typeof(p_payload->'connectionIds') IS DISTINCT FROM 'array' THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  IF jsonb_array_length(p_payload->'connectionIds')>100 THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'connectionIds') a
    WHERE jsonb_typeof(a.value)<>'string' OR (a.value#>>'{}') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  RETURN coalesce((SELECT jsonb_agg(jsonb_build_object('id',x.id,'createdBy',x.owner_user_id,'createdByName',a.name))
    FROM public.source_connections x JOIN public.auth_users a ON a.id=x.owner_user_id
    WHERE x.workspace_id=w AND x.id IN (SELECT (value#>>'{}')::uuid FROM jsonb_array_elements(p_payload->'connectionIds'))),'[]');
 END IF;
 PERFORM id FROM public.auth_users"""),
        ("'canDisconnect',x.owner_user_id=u OR member_role='owner',",
         "'canDisconnect',x.owner_user_id=u OR member_role='owner',\n   'canReconnect',x.owner_user_id=u OR (member_role='owner' AND NOT x.enabled AND x.status='disabled' AND x.credential_blob IS NULL),"),
        ("FROM public.source_connections x WHERE x.workspace_id=w)",
         "FROM public.source_connections x WHERE x.workspace_id=w AND x.retired_at IS NULL)"),
        ("WHERE workspace_id=w AND provider=provider_name FOR UPDATE;",
         "WHERE workspace_id=w AND provider=provider_name AND retired_at IS NULL FOR UPDATE;"),
        ("ELSIF c.owner_user_id<>u THEN RETURN jsonb_build_object('error','connection_owned_by_another_user'); END IF;", """ELSIF c.owner_user_id<>u THEN
   IF member_role<>'owner' OR c.enabled OR c.status<>'disabled' OR c.credential_blob IS NOT NULL
     THEN RETURN jsonb_build_object('error','connection_owned_by_another_user'); END IF;
   -- Never reuse another account's source_items namespace or encrypted state.
   UPDATE public.source_connections SET retired_at=clock_timestamp(),scope_revision=scope_revision+1,
    credential_blob=NULL,cursor_blob=NULL,account_label=NULL,resources='[]',updated_at=clock_timestamp() WHERE id=c.id;
   DELETE FROM public.source_auth_states WHERE workspace_id=w AND connection_id=c.id;
   UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,cursor_blob=NULL,completed_at=clock_timestamp()
    WHERE workspace_id=w AND connection_id=c.id AND status IN ('queued','processing','retry_wait');
   INSERT INTO public.source_connections(id,workspace_id,provider,owner_user_id)
    VALUES(p_id,w,provider_name,u) RETURNING * INTO c;
  END IF;"""),
        ("IF NOT FOUND OR c.owner_user_id<>u OR c.scope_revision<>s.scope_revision",
         "IF NOT FOUND OR c.retired_at IS NOT NULL OR c.owner_user_id<>u OR c.scope_revision<>s.scope_revision"),
        ("IF NOT FOUND THEN RETURN jsonb_build_object('error','source_not_found'); END IF;",
         "IF NOT FOUND OR c.retired_at IS NOT NULL THEN RETURN jsonb_build_object('error','source_not_found'); END IF;"),
    ])
    patch("source_worker_step(uuid,uuid,bigint,text,jsonb)", [
        ("record jsonb; chunk jsonb;", "record jsonb; chunk jsonb; actor_name text; creator_meta jsonb; original_meta jsonb;"),
        ("IF NOT c.enabled OR c.credential_blob IS NULL", "IF c.retired_at IS NOT NULL OR NOT c.enabled OR c.credential_blob IS NULL"),
        ("PERFORM id FROM public.auth_users WHERE id=j.owner_user_id AND NOT disabled FOR SHARE;",
         "SELECT name INTO actor_name FROM public.auth_users WHERE id=j.owner_user_id AND NOT disabled FOR SHARE;"),
        ("SELECT * INTO s FROM public.source_items WHERE workspace_id=j.workspace_id", """creator_meta:=jsonb_build_object('createdBy',j.owner_user_id,'createdByName',actor_name);
  record:=jsonb_set(record,'{metadata}',((record->'metadata')-'createdBy'-'createdByName')||creator_meta);
  SELECT * INTO s FROM public.source_items WHERE workspace_id=j.workspace_id"""),
        ("doc_id:=s.document_id;", """doc_id:=s.document_id;
   SELECT snapshot_metadata INTO original_meta FROM public.document_versions
    WHERE workspace_id=j.workspace_id AND document_id=doc_id AND version_number=1;
   IF original_meta->>'createdBy'=j.owner_user_id AND jsonb_typeof(original_meta->'createdByName')='string' THEN
    record:=jsonb_set(record,'{metadata,createdByName}',original_meta->'createdByName');
   END IF;"""),
    ])


def downgrade():
    raise RuntimeError("Source bindings and authorship contain history; restore a reviewed backup instead.")
