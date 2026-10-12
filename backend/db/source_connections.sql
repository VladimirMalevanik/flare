-- DATA-003: selected shared snapshots, private credentials and bounded sync jobs.
CREATE TABLE public.source_connections (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
 provider text NOT NULL CHECK(provider IN ('slack','gmail','drive','notion','github')),
 owner_user_id text NOT NULL REFERENCES public.auth_users(id), account_label text,
 credential_blob text CHECK(length(credential_blob)<=24000), cursor_blob text CHECK(length(cursor_blob)<=24000),
 scope_revision bigint NOT NULL DEFAULT 1, enabled boolean NOT NULL DEFAULT false,
 resources jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(selected_resources)='array' AND jsonb_array_length(selected_resources)<=20),
 policy jsonb NOT NULL DEFAULT '{}', status text NOT NULL DEFAULT 'pending'
  CHECK(status IN ('pending','connected','ready','syncing','error','disabled')),
 github_installation_id bigint, github_repository_id bigint, error_code text,
 last_sync_at timestamptz, next_sync_at timestamptz NOT NULL DEFAULT now(), last_result jsonb,
 auth_checked_at timestamptz NOT NULL DEFAULT '-infinity',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(workspace_id,id), UNIQUE(workspace_id,provider)
);
CREATE INDEX source_due ON public.source_connections(next_sync_at) WHERE enabled;
CREATE TABLE public.source_auth_states (
 state_hash text PRIMARY KEY CHECK(state_hash ~ '^[0-9a-f]{64}$'), workspace_id uuid NOT NULL,
 connection_id uuid NOT NULL, user_id text NOT NULL, scope_revision bigint NOT NULL,
 pending_blob text NOT NULL CHECK(length(pending_blob)<=24000), expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(workspace_id,connection_id) REFERENCES public.source_connections(workspace_id,id)
);
CREATE INDEX source_state_expiry ON public.source_auth_states(expires_at);
CREATE TABLE public.source_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL, connection_id uuid NOT NULL,
 owner_user_id text NOT NULL, scope_revision bigint NOT NULL, generation bigint NOT NULL DEFAULT 0,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','processing','retry_wait','completed','failed','cancelled')),
 cursor_blob text CHECK(length(cursor_blob)<=24000), lease_token uuid, lease_expires_at timestamptz,
 available_at timestamptz NOT NULL DEFAULT now(), deadline timestamptz NOT NULL DEFAULT now()+interval '1 hour',
 attempts integer NOT NULL DEFAULT 0, pages integer NOT NULL DEFAULT 0,
 added integer NOT NULL DEFAULT 0, updated integer NOT NULL DEFAULT 0, unchanged integer NOT NULL DEFAULT 0,
 skipped integer NOT NULL DEFAULT 0, conflicts integer NOT NULL DEFAULT 0, more boolean NOT NULL DEFAULT false,
 error_code text, created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(workspace_id,id),
 FOREIGN KEY(workspace_id,connection_id) REFERENCES public.source_connections(workspace_id,id)
);
CREATE UNIQUE INDEX source_one_active ON public.source_jobs(workspace_id,connection_id)
 WHERE status IN ('queued','processing','retry_wait');
CREATE INDEX source_queue ON public.source_jobs(available_at,created_at) WHERE status IN ('queued','processing','retry_wait');
CREATE TABLE public.source_items (
 workspace_id uuid NOT NULL, connection_id uuid NOT NULL, external_id text NOT NULL CHECK(octet_length(external_id)<=500),
 document_id uuid NOT NULL, last_version_id uuid NOT NULL, content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(workspace_id,connection_id,external_id),
 FOREIGN KEY(workspace_id,connection_id) REFERENCES public.source_connections(workspace_id,id),
 FOREIGN KEY(workspace_id,document_id) REFERENCES public.documents(workspace_id,id),
 FOREIGN KEY(workspace_id,document_id,last_version_id) REFERENCES public.document_versions(workspace_id,document_id,id)
);
CREATE TABLE public.source_worker_health (
 name text PRIMARY KEY CHECK(name='worker'), providers text[] NOT NULL,
 last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION public.source_api(p_action text,p_id uuid,p_payload jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
 u text:=nullif(current_setting('app.user_id',true),''); member_role text;
 c public.source_connections; s public.source_auth_states; j public.source_jobs;
 g public.github_connections; provider_name text; selected_resources jsonb;
BEGIN
 PERFORM id FROM public.auth_users WHERE id=u AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 SELECT role INTO member_role FROM public.workspace_members WHERE workspace_id=w AND user_id=u FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 IF p_action='health' THEN
  RETURN coalesce((SELECT jsonb_build_object('providers',providers,'available',last_seen_at>clock_timestamp()-interval '5 minutes') FROM public.source_worker_health WHERE name='worker'),jsonb_build_object('providers','[]'::jsonb,'available',false));
 END IF;
 IF p_action='list' THEN
  RETURN coalesce((SELECT jsonb_agg(jsonb_build_object(
   'id',x.id,'provider',x.provider,'owner',x.owner_user_id=u,'canDisconnect',x.owner_user_id=u OR member_role='owner',
   'accountLabel',CASE WHEN x.owner_user_id=u THEN x.account_label ELSE NULL END,
   'scopeRevision',x.scope_revision,'status',x.status,'enabled',x.enabled,'resources',x.resources,
   'lastSyncAt',x.last_sync_at,'nextSyncAt',CASE WHEN x.enabled THEN x.next_sync_at ELSE NULL END,
   'errorCode',x.error_code,'lastResult',x.last_result,
   'job',(SELECT jsonb_build_object('id',q.id,'status',q.status,'added',q.added,'updated',q.updated,
    'unchanged',q.unchanged,'skipped',q.skipped,'conflicts',q.conflicts,'more',q.more,'errorCode',q.error_code)
    FROM public.source_jobs q WHERE q.workspace_id=w AND q.connection_id=x.id ORDER BY q.created_at DESC LIMIT 1)) ORDER BY x.created_at)
    FROM public.source_connections x WHERE x.workspace_id=w),'[]');
 END IF;
 IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR octet_length(p_payload::text)>100000 THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
 IF p_action NOT IN ('disconnect') AND member_role NOT IN ('owner','editor') THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 IF p_action='reserve' THEN
  provider_name:=p_payload->>'provider';
  IF provider_name IS NULL OR provider_name NOT IN ('slack','gmail','drive','notion','github') THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  PERFORM pg_advisory_xact_lock(hashtext('source-reserve:'||w::text||':'||provider_name));
  SELECT * INTO c FROM public.source_connections WHERE workspace_id=w AND provider=provider_name FOR UPDATE;
  IF NOT FOUND THEN
   INSERT INTO public.source_connections(id,workspace_id,provider,owner_user_id)
    VALUES(p_id,w,provider_name,u) RETURNING * INTO c;
  ELSIF c.owner_user_id<>u THEN RETURN jsonb_build_object('error','connection_owned_by_another_user'); END IF;
  RETURN jsonb_build_object('id',c.id,'scopeRevision',c.scope_revision,'provider',c.provider);
 END IF;
 IF p_action='consume_state' THEN
  DELETE FROM public.source_auth_states WHERE state_hash=p_payload->>'stateHash'
   AND workspace_id=w AND user_id=u AND expires_at>clock_timestamp() RETURNING * INTO s;
  IF NOT FOUND THEN RETURN jsonb_build_object('error','invalid_state'); END IF;
  SELECT * INTO c FROM public.source_connections WHERE workspace_id=w AND id=s.connection_id FOR UPDATE;
  IF NOT FOUND OR c.owner_user_id<>u OR c.scope_revision<>s.scope_revision OR c.provider<>p_payload->>'provider' THEN RETURN jsonb_build_object('error','invalid_state'); END IF;
  RETURN jsonb_build_object('id',c.id,'provider',c.provider,'scopeRevision',s.scope_revision,'pendingBlob',s.pending_blob);
 END IF;
 SELECT * INTO c FROM public.source_connections WHERE workspace_id=w AND id=p_id FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','source_not_found'); END IF;
 IF p_action='disconnect' THEN
  IF c.owner_user_id<>u AND member_role<>'owner' THEN RETURN jsonb_build_object('error','forbidden'); END IF;
  UPDATE public.source_connections SET credential_blob=NULL,cursor_blob=NULL,resources='[]',enabled=false,
   scope_revision=scope_revision+1,status='disabled',error_code=NULL,updated_at=clock_timestamp() WHERE id=c.id;
  DELETE FROM public.source_auth_states WHERE workspace_id=w AND connection_id=c.id;
  UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp()
   WHERE workspace_id=w AND connection_id=c.id AND status IN ('queued','processing','retry_wait');
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF c.owner_user_id<>u THEN RETURN jsonb_build_object('error','connection_owned_by_another_user'); END IF;
 IF p_action='credentials' THEN
  RETURN jsonb_build_object('id',c.id,'provider',c.provider,'scopeRevision',c.scope_revision,
   'credentialBlob',c.credential_blob,'cursorBlob',c.cursor_blob,'resources',c.resources,'enabled',c.enabled);
 END IF;
 IF p_action='state' THEN
  IF (p_payload->>'expectedRevision')::bigint IS DISTINCT FROM c.scope_revision THEN RETURN jsonb_build_object('error','selection_changed'); END IF;
  IF (SELECT count(*) FROM public.source_auth_states WHERE workspace_id=w AND user_id=u AND expires_at>clock_timestamp())>=20 THEN RETURN jsonb_build_object('error','rate_limited'); END IF;
  INSERT INTO public.source_auth_states(state_hash,workspace_id,connection_id,user_id,scope_revision,pending_blob,expires_at)
   VALUES(p_payload->>'stateHash',w,c.id,u,c.scope_revision,p_payload->>'pendingBlob',clock_timestamp()+interval '10 minutes');
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF p_action IN ('complete','complete_github','select','token_refresh') AND (p_payload->>'expectedRevision')::bigint IS DISTINCT FROM c.scope_revision THEN RETURN jsonb_build_object('error','selection_changed'); END IF;
 IF p_action IN ('complete','complete_github') THEN
  IF p_payload->>'credentialBlob' IS NULL OR p_payload->>'accountLabel' IS NULL OR length(p_payload->>'credentialBlob') NOT BETWEEN 1 AND 24000 OR length(p_payload->>'accountLabel') NOT BETWEEN 1 AND 160 THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  IF p_action='complete_github' THEN
   IF c.provider<>'github' OR p_payload->>'installationId' IS NULL OR p_payload->>'repositoryId' IS NULL THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
   SELECT * INTO g FROM public.github_connections WHERE workspace_id=w AND status='connected' AND repository_id IS NOT NULL FOR SHARE;
   IF NOT FOUND OR g.installation_id<>(p_payload->>'installationId')::bigint OR g.repository_id<>(p_payload->>'repositoryId')::bigint THEN RETURN jsonb_build_object('error','selection_changed'); END IF;
  ELSIF c.provider='github' THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  UPDATE public.source_connections SET credential_blob=p_payload->>'credentialBlob',account_label=p_payload->>'accountLabel',
   enabled=false,resources='[]',cursor_blob=NULL,status='connected',error_code=NULL,scope_revision=scope_revision+1,
   github_installation_id=g.installation_id,github_repository_id=g.repository_id,policy=p_payload->'policy',updated_at=clock_timestamp() WHERE id=c.id;
  UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp()
   WHERE workspace_id=w AND connection_id=c.id AND status IN ('queued','processing','retry_wait');
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF p_action='token_refresh' THEN
  IF c.credential_blob IS NULL OR p_payload->>'credentialBlob' IS NULL OR length(p_payload->>'credentialBlob') NOT BETWEEN 1 AND 24000 THEN RETURN jsonb_build_object('error','authorization_lost'); END IF;
  UPDATE public.source_connections SET credential_blob=p_payload->>'credentialBlob' WHERE id=c.id;
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF c.credential_blob IS NULL THEN RETURN jsonb_build_object('error','authorization_lost'); END IF;
 IF p_action='select' THEN
  selected_resources:=p_payload->'resources';
  IF jsonb_typeof(selected_resources) IS DISTINCT FROM 'array' OR jsonb_array_length(selected_resources)>20 OR (jsonb_array_length(selected_resources)>0 AND p_payload->'shareWithWorkspace' IS DISTINCT FROM 'true'::jsonb) THEN RETURN jsonb_build_object('error','selection_consent_required'); END IF;
  UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp()
   WHERE workspace_id=w AND connection_id=c.id AND status IN ('queued','processing','retry_wait');
  UPDATE public.source_connections SET resources=selected_resources,cursor_blob=NULL,scope_revision=scope_revision+1,
   enabled=jsonb_array_length(selected_resources)>0,status=CASE WHEN jsonb_array_length(selected_resources)>0 THEN 'ready' ELSE 'connected' END,
   next_sync_at=clock_timestamp(),error_code=NULL,updated_at=clock_timestamp() WHERE id=c.id;
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF p_action='cancel' THEN
  UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp()
   WHERE workspace_id=w AND connection_id=c.id AND status IN ('queued','processing','retry_wait');
  UPDATE public.source_connections SET scope_revision=scope_revision+1,status='ready',
   next_sync_at=clock_timestamp()+interval '1 hour',updated_at=clock_timestamp() WHERE id=c.id;
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF p_action='enqueue' THEN
  IF NOT c.enabled OR jsonb_array_length(c.resources)=0 THEN RETURN jsonb_build_object('error','no_resources_selected'); END IF;
  IF NOT EXISTS(SELECT 1 FROM public.source_worker_health WHERE name='worker' AND last_seen_at>clock_timestamp()-interval '5 minutes' AND c.provider=ANY(providers)) THEN RETURN jsonb_build_object('error','source_worker_unavailable'); END IF;
  IF c.error_code='rate_limited' AND c.next_sync_at>clock_timestamp() THEN RETURN jsonb_build_object('error','rate_limited'); END IF;
  SELECT * INTO j FROM public.source_jobs WHERE workspace_id=w AND connection_id=c.id AND status IN ('queued','processing','retry_wait');
  IF NOT FOUND THEN
   INSERT INTO public.source_jobs(workspace_id,connection_id,owner_user_id,scope_revision,cursor_blob)
    VALUES(w,c.id,u,c.scope_revision,c.cursor_blob) RETURNING * INTO j;
  END IF;
  RETURN jsonb_build_object('id',j.id,'status',j.status);
 END IF;
 RETURN jsonb_build_object('error','invalid_request');
END $$;

CREATE FUNCTION public.claim_source_job(p_providers text[],p_concurrency integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c public.source_connections; j public.source_jobs; g public.github_connections;
BEGIN
 IF p_concurrency IS NULL OR p_providers IS NULL OR p_concurrency NOT BETWEEN 1 AND 4 OR cardinality(p_providers)>5 THEN RETURN NULL; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtext('flare-source-claim')) THEN RETURN NULL; END IF;
 INSERT INTO public.source_worker_health(name,providers,last_seen_at) VALUES('worker',p_providers,clock_timestamp())
  ON CONFLICT(name) DO UPDATE SET providers=excluded.providers,last_seen_at=excluded.last_seen_at;
 DELETE FROM public.source_auth_states WHERE state_hash IN (SELECT state_hash FROM public.source_auth_states WHERE expires_at<clock_timestamp() ORDER BY expires_at LIMIT 100);
 FOR c IN SELECT x.* FROM public.source_connections x WHERE x.credential_blob IS NOT NULL ORDER BY x.auth_checked_at LIMIT 100 FOR UPDATE SKIP LOCKED LOOP
  PERFORM set_config('app.workspace_id',c.workspace_id::text,true),set_config('app.user_id',c.owner_user_id,true);
  IF NOT EXISTS(SELECT 1 FROM public.auth_users a JOIN public.workspace_members m ON m.user_id=a.id
   WHERE a.id=c.owner_user_id AND NOT a.disabled AND m.workspace_id=c.workspace_id AND m.role IN ('owner','editor')) THEN
   UPDATE public.source_connections SET credential_blob=NULL,cursor_blob=NULL,enabled=false,scope_revision=scope_revision+1,status='disabled',error_code='authorization_lost' WHERE id=c.id;
   UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp() WHERE connection_id=c.id AND status IN ('queued','processing','retry_wait');
  END IF;
  UPDATE public.source_connections SET auth_checked_at=clock_timestamp() WHERE id=c.id;
 END LOOP;
 INSERT INTO public.source_jobs(workspace_id,connection_id,owner_user_id,scope_revision,cursor_blob)
  SELECT x.workspace_id,x.id,x.owner_user_id,x.scope_revision,x.cursor_blob FROM public.source_connections x
  WHERE x.enabled AND x.credential_blob IS NOT NULL AND x.provider=ANY(p_providers) AND x.next_sync_at<=clock_timestamp()
   AND NOT EXISTS(SELECT 1 FROM public.source_jobs q WHERE q.connection_id=x.id AND q.status IN ('queued','processing','retry_wait'))
  ORDER BY x.next_sync_at LIMIT 100 ON CONFLICT DO NOTHING;
 IF (SELECT count(*) FROM public.source_jobs WHERE status='processing' AND lease_expires_at>clock_timestamp())>=p_concurrency THEN RETURN NULL; END IF;
 FOR j IN SELECT q.* FROM public.source_jobs q JOIN public.source_connections x ON x.id=q.connection_id
  WHERE x.provider=ANY(p_providers) AND x.enabled AND q.available_at<=clock_timestamp()
   AND (q.status IN ('queued','retry_wait') OR q.status='processing' AND q.lease_expires_at<=clock_timestamp())
  ORDER BY q.available_at,q.created_at LIMIT 100 LOOP
  SELECT * INTO c FROM public.source_connections WHERE id=j.connection_id FOR UPDATE;
  SELECT * INTO j FROM public.source_jobs WHERE id=j.id FOR UPDATE;
  IF NOT FOUND OR j.status NOT IN ('queued','retry_wait','processing') OR (j.status='processing' AND j.lease_expires_at>clock_timestamp()) THEN CONTINUE; END IF;
  IF c.scope_revision<>j.scope_revision OR c.credential_blob IS NULL THEN
   UPDATE public.source_jobs SET status='cancelled',completed_at=clock_timestamp() WHERE id=j.id; CONTINUE;
  END IF;
  IF j.deadline<=clock_timestamp() OR j.attempts>=5 THEN
   UPDATE public.source_jobs SET status='failed',error_code='sync_deadline',completed_at=clock_timestamp() WHERE id=j.id;
   UPDATE public.source_connections SET status='error',error_code='sync_deadline',next_sync_at=clock_timestamp()+interval '1 hour' WHERE id=c.id; CONTINUE;
  END IF;
  IF EXISTS(SELECT 1 FROM public.source_jobs q WHERE q.workspace_id=j.workspace_id AND q.id<>j.id AND q.status='processing' AND q.lease_expires_at>clock_timestamp()) THEN CONTINUE; END IF;
  PERFORM set_config('app.workspace_id',j.workspace_id::text,true),set_config('app.user_id',j.owner_user_id,true);
  PERFORM id FROM public.auth_users a JOIN public.workspace_members m ON m.user_id=a.id WHERE a.id=j.owner_user_id AND NOT a.disabled AND m.workspace_id=j.workspace_id AND m.role IN ('owner','editor') FOR SHARE;
  IF NOT FOUND THEN
   UPDATE public.source_connections SET credential_blob=NULL,cursor_blob=NULL,enabled=false,scope_revision=scope_revision+1,status='disabled',error_code='authorization_lost' WHERE id=c.id;
   UPDATE public.source_jobs SET status='cancelled',lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp() WHERE id=j.id; CONTINUE;
  END IF;
  IF c.provider='github' THEN
   SELECT * INTO g FROM public.github_connections WHERE workspace_id=j.workspace_id AND status='connected' AND installation_id=c.github_installation_id AND repository_id=c.github_repository_id FOR SHARE;
   IF NOT FOUND THEN
    UPDATE public.source_connections SET credential_blob=NULL,enabled=false,status='error',scope_revision=scope_revision+1,error_code='repository_changed' WHERE id=c.id;
    UPDATE public.source_jobs SET status='cancelled',completed_at=clock_timestamp() WHERE id=j.id; CONTINUE;
   END IF;
  END IF;
  UPDATE public.source_jobs SET status='processing',lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+interval '180 seconds',generation=generation+1,attempts=attempts+1 WHERE id=j.id RETURNING * INTO j;
  UPDATE public.source_connections SET status='syncing',error_code=NULL WHERE id=c.id;
  RETURN jsonb_build_object('id',j.id,'workspace_id',j.workspace_id,'connection_id',c.id,'user_id',c.owner_user_id,
   'provider',c.provider,'scope_revision',c.scope_revision,'generation',j.generation,'lease_token',j.lease_token,
   'credential_blob',c.credential_blob,'cursor_blob',j.cursor_blob,'resources',c.resources,'policy',c.policy);
 END LOOP;
 RETURN NULL;
END $$;

CREATE FUNCTION public.source_worker_step(p_id uuid,p_lease uuid,p_generation bigint,p_action text,p_payload jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE j public.source_jobs; c public.source_connections; s public.source_items; d public.documents;
 record jsonb; chunk jsonb; doc_id uuid; version_id uuid; version_no integer;
 a integer:=0; updated_count integer:=0; same integer:=0; conflict_count integer:=0;
 delay integer; has_more boolean; counts jsonb; g public.github_connections; stored_bytes bigint; document_bytes bigint;
BEGIN
 SELECT * INTO j FROM public.source_jobs WHERE id=p_id;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
 SELECT * INTO c FROM public.source_connections WHERE id=j.connection_id FOR UPDATE;
 SELECT * INTO j FROM public.source_jobs WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR j.status<>'processing' OR j.lease_token IS DISTINCT FROM p_lease OR j.generation<>p_generation OR j.lease_expires_at<=clock_timestamp() OR j.deadline<=clock_timestamp() THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
 IF NOT c.enabled OR c.credential_blob IS NULL OR c.scope_revision<>j.scope_revision THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
 PERFORM set_config('app.workspace_id',j.workspace_id::text,true),set_config('app.user_id',j.owner_user_id,true);
 PERFORM id FROM public.auth_users WHERE id=j.owner_user_id AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','authorization_lost'); END IF;
 PERFORM user_id FROM public.workspace_members WHERE workspace_id=j.workspace_id AND user_id=j.owner_user_id AND role IN ('owner','editor') FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','authorization_lost'); END IF;
 IF c.provider='github' THEN
  SELECT * INTO g FROM public.github_connections WHERE workspace_id=j.workspace_id AND status='connected' AND installation_id=c.github_installation_id AND repository_id=c.github_repository_id FOR SHARE;
  IF NOT FOUND THEN RETURN jsonb_build_object('error','repository_changed'); END IF;
 END IF;
 IF p_action='credentials' THEN
  IF p_payload->>'credentialBlob' IS NULL OR length(p_payload->>'credentialBlob') NOT BETWEEN 1 AND 24000 THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
  UPDATE public.source_connections SET credential_blob=p_payload->>'credentialBlob' WHERE id=c.id;
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF p_action='error' THEN
  delay:=coalesce((p_payload->>'delay')::integer,60);
  IF delay<1 OR delay>86400 OR p_payload->'reconnect'='true'::jsonb OR j.attempts>=5 THEN
   UPDATE public.source_jobs SET status='failed',error_code=p_payload->>'code',completed_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL WHERE id=j.id;
   UPDATE public.source_connections SET status='error',enabled=CASE WHEN p_payload->'reconnect'='true'::jsonb OR delay>86400 THEN false ELSE enabled END,
    error_code=p_payload->>'code',next_sync_at=clock_timestamp()+interval '1 hour' WHERE id=c.id;
  ELSE
   UPDATE public.source_jobs SET status='retry_wait',available_at=clock_timestamp()+make_interval(secs=>delay),error_code=p_payload->>'code',lease_token=NULL,lease_expires_at=NULL WHERE id=j.id;
   UPDATE public.source_connections SET status='error',error_code=p_payload->>'code',next_sync_at=clock_timestamp()+make_interval(secs=>delay) WHERE id=c.id;
  END IF;
  RETURN jsonb_build_object('ok',true);
 END IF;
 IF p_action<>'publish' OR jsonb_typeof(p_payload->'documents') IS DISTINCT FROM 'array' OR jsonb_array_length(p_payload->'documents')>15 OR octet_length(p_payload::text)>4000000 THEN RETURN jsonb_build_object('error','invalid_request'); END IF;
 -- Serialize against ZIP/source publication and bound immutable-version storage.
 PERFORM id FROM public.workspaces WHERE id=j.workspace_id FOR UPDATE;
 SELECT coalesce(sum(octet_length(k.content)),0) INTO stored_bytes FROM public.chunks k WHERE k.workspace_id=j.workspace_id;
 FOR record IN SELECT value FROM jsonb_array_elements(p_payload->'documents') LOOP
  IF record->>'externalId' IS NULL OR record->>'title' IS NULL OR record->>'hash' IS NULL OR record->>'contentHash' IS NULL OR length(record->>'externalId') NOT BETWEEN 1 AND 500 OR length(record->>'title') NOT BETWEEN 1 AND 300 OR record->>'hash' !~ '^[0-9a-f]{64}$'
   OR record->>'contentHash' !~ '^[0-9a-f]{64}$' OR jsonb_typeof(record->'metadata') IS DISTINCT FROM 'object' OR jsonb_typeof(record->'chunks') IS DISTINCT FROM 'array'
   OR jsonb_array_length(record->'chunks') NOT BETWEEN 1 AND 100 OR octet_length((record->'chunks')::text)>450000
   OR record->'metadata'->>'sourceProvider' IS DISTINCT FROM c.provider
   OR record->'metadata'->>'sourceConnectionId' IS DISTINCT FROM c.id::text THEN RAISE EXCEPTION 'Invalid source document' USING ERRCODE='23514'; END IF;
  SELECT * INTO s FROM public.source_items WHERE workspace_id=j.workspace_id AND connection_id=c.id AND external_id=record->>'externalId' FOR UPDATE;
  IF FOUND THEN
   SELECT * INTO d FROM public.documents WHERE workspace_id=j.workspace_id AND id=s.document_id FOR UPDATE;
   IF d.deleted_at IS NOT NULL OR d.current_version_id IS DISTINCT FROM s.last_version_id THEN conflict_count:=conflict_count+1; CONTINUE; END IF;
   IF s.content_hash=record->>'hash' THEN same:=same+1; CONTINUE; END IF;
   doc_id:=s.document_id;
   SELECT version_number+1 INTO version_no FROM public.document_versions WHERE workspace_id=j.workspace_id AND document_id=doc_id AND id=d.current_version_id;
   updated_count:=updated_count+1;
  ELSE
   doc_id:=gen_random_uuid(); version_no:=1; a:=a+1;
   INSERT INTO public.documents(id,workspace_id,title,source_type,source_url,metadata)
    VALUES(doc_id,j.workspace_id,record->>'title','file',record->>'url',record->'metadata');
  END IF;
  SELECT coalesce(sum(octet_length(k.value->>'content')),0) INTO document_bytes FROM jsonb_array_elements(record->'chunks') k;
  IF stored_bytes+document_bytes>coalesce((c.policy->>'workspaceBytes')::bigint,500000000) THEN
   RAISE EXCEPTION 'workspace_storage_limit' USING ERRCODE='54000';
  END IF;
  stored_bytes:=stored_bytes+document_bytes;
  version_id:=gen_random_uuid();
  INSERT INTO public.document_versions(id,workspace_id,document_id,version_number,content_hash,parser_version,snapshot_title,snapshot_source_url,snapshot_metadata,state)
   VALUES(version_id,j.workspace_id,doc_id,version_no,record->>'contentHash','source-text-v1',record->>'title',record->>'url',record->'metadata','processing');
  FOR chunk IN SELECT value FROM jsonb_array_elements(record->'chunks') LOOP
   IF chunk->>'content' IS NULL OR chunk->>'ordinal' IS NULL OR length(btrim(chunk->>'content'))=0 OR octet_length(chunk->>'content')>200000 OR jsonb_typeof(chunk->'locator') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Invalid source chunk' USING ERRCODE='23514'; END IF;
   INSERT INTO public.chunks(workspace_id,document_version_id,ordinal,content,locator)
    VALUES(j.workspace_id,version_id,(chunk->>'ordinal')::integer,chunk->>'content',chunk->'locator');
  END LOOP;
  UPDATE public.document_versions SET state='ready' WHERE id=version_id;
  UPDATE public.documents SET title=record->>'title',source_url=record->>'url',metadata=record->'metadata',current_version_id=version_id,updated_at=clock_timestamp() WHERE id=doc_id;
  INSERT INTO public.source_items(workspace_id,connection_id,external_id,document_id,last_version_id,content_hash)
   VALUES(j.workspace_id,c.id,record->>'externalId',doc_id,version_id,record->>'hash')
   ON CONFLICT(workspace_id,connection_id,external_id) DO UPDATE SET last_version_id=excluded.last_version_id,content_hash=excluded.content_hash;
 END LOOP;
 delay:=coalesce((p_payload->>'delay')::integer,0);
 IF delay NOT BETWEEN 0 AND 86400 THEN RAISE EXCEPTION 'Invalid source delay'; END IF;
 has_more:=p_payload->>'cursorBlob' IS NOT NULL;
 UPDATE public.source_jobs SET added=added+a,updated=updated+updated_count,unchanged=unchanged+same,conflicts=conflicts+conflict_count,
  skipped=skipped+coalesce((p_payload->>'skipped')::integer,0),pages=pages+1,attempts=0,cursor_blob=p_payload->>'cursorBlob',
  lease_token=NULL,lease_expires_at=NULL,more=has_more WHERE id=j.id RETURNING * INTO j;
 counts:=jsonb_build_object('added',j.added,'updated',j.updated,'unchanged',j.unchanged,'skipped',j.skipped,'conflicts',j.conflicts,'more',has_more);
 IF has_more AND j.added+j.updated+j.unchanged+j.skipped+j.conflicts<200 AND j.pages<100 THEN
  UPDATE public.source_jobs SET status='queued',available_at=clock_timestamp()+make_interval(secs=>delay) WHERE id=j.id;
 ELSE
  UPDATE public.source_jobs SET status='completed',completed_at=clock_timestamp() WHERE id=j.id;
  UPDATE public.source_connections SET status='ready',error_code=NULL,last_sync_at=clock_timestamp(),last_result=counts,
   next_sync_at=clock_timestamp()+make_interval(secs=>coalesce((c.policy->>'syncIntervalSeconds')::integer,3600)) WHERE id=c.id;
 END IF;
 UPDATE public.source_connections SET cursor_blob=p_payload->>'cursorBlob',updated_at=clock_timestamp() WHERE id=c.id;
 RETURN counts;
END $$;
