-- DATA-002 migration 0019 snapshot. Do not mutate after release.
CREATE TABLE public.import_packages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
 requested_by_user_id text NOT NULL REFERENCES public.auth_users(id), source_kind text NOT NULL CHECK(source_kind IN ('notion','obsidian')),
 file_name text NOT NULL, file_size bigint NOT NULL CHECK(file_size>0), request_key uuid NOT NULL,
 policy jsonb NOT NULL, status text NOT NULL DEFAULT 'uploading' CHECK(status IN ('uploading','staged','queued','processing','retry_wait','completed','completed_with_skips','failed','cancelled','expired','duplicate')),
 phase text NOT NULL DEFAULT 'upload', archive_hash text, canonical_id uuid, object_key text,
 upload_token uuid, upload_expires_at timestamptz, attempts int NOT NULL DEFAULT 0,
 lease_token uuid, generation bigint NOT NULL DEFAULT 0, lease_expires_at timestamptz,
 available_at timestamptz NOT NULL DEFAULT now(), job_deadline timestamptz,
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 error_code text, retryable boolean NOT NULL DEFAULT false,
 entry_count int, prepared_count int NOT NULL DEFAULT 0, skipped_count int NOT NULL DEFAULT 0,
 published_count int NOT NULL DEFAULT 0, chunk_count int NOT NULL DEFAULT 0, reserved_bytes bigint NOT NULL DEFAULT 0,
 UNIQUE(workspace_id,id), UNIQUE(workspace_id,request_key),
 FOREIGN KEY(workspace_id,canonical_id) REFERENCES public.import_packages(workspace_id,id)
);
CREATE UNIQUE INDEX import_package_exact ON public.import_packages(workspace_id,source_kind,archive_hash)
 WHERE archive_hash IS NOT NULL AND status IN ('queued','processing','retry_wait','completed','completed_with_skips');
CREATE INDEX import_queue ON public.import_packages(available_at,created_at) WHERE status IN ('queued','processing','retry_wait');
CREATE TABLE public.import_package_entries (
 workspace_id uuid NOT NULL, package_id uuid NOT NULL, ordinal int NOT NULL CHECK(ordinal>=0),
 path text NOT NULL, canonical_path text NOT NULL, file_bytes bigint NOT NULL CHECK(file_bytes>=0),
 skip_reason text, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','prepared','skipped','published')),
 file_hash text, parsed jsonb, document_id uuid, version_id uuid,
 PRIMARY KEY(workspace_id,package_id,ordinal), UNIQUE(workspace_id,package_id,canonical_path),
 FOREIGN KEY(workspace_id,package_id) REFERENCES public.import_packages(workspace_id,id),
 FOREIGN KEY(workspace_id,document_id) REFERENCES public.documents(workspace_id,id),
 FOREIGN KEY(workspace_id,document_id,version_id) REFERENCES public.document_versions(workspace_id,document_id,id)
);
CREATE TABLE public.import_objects (
 key text PRIMARY KEY CHECK(key ~ '^[0-9a-f]{32}-[0-9a-f]{32}$'), workspace_id uuid NOT NULL,
 package_id uuid NOT NULL, status text NOT NULL DEFAULT 'writing' CHECK(status IN ('writing','sealed','deleting','deleted')),
 bytes bigint NOT NULL CHECK(bytes>0), expires_at timestamptz NOT NULL,
 cleanup_token uuid, cleanup_expires_at timestamptz, available_at timestamptz NOT NULL DEFAULT now(),
 attempts int NOT NULL DEFAULT 0, overdue boolean NOT NULL DEFAULT false,
 FOREIGN KEY(workspace_id,package_id) REFERENCES public.import_packages(workspace_id,id)
);
CREATE TABLE public.import_publications (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, workspace_id uuid NOT NULL,
 package_id uuid NOT NULL UNIQUE, requested_by_user_id text NOT NULL, source_kind text NOT NULL,
 published_at timestamptz NOT NULL DEFAULT now(), source_count int NOT NULL, chunk_count int NOT NULL,
 FOREIGN KEY(workspace_id,package_id) REFERENCES public.import_packages(workspace_id,id)
);
ALTER TABLE public.documents ADD COLUMN import_package_id uuid;
ALTER TABLE public.documents ADD FOREIGN KEY(workspace_id,import_package_id) REFERENCES public.import_packages(workspace_id,id);
CREATE FUNCTION public.guard_import_provenance() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF NEW.import_package_id IS DISTINCT FROM OLD.import_package_id THEN RAISE EXCEPTION 'Immutable import provenance' USING ERRCODE='23514'; END IF;
 RETURN NEW; END $$;
REVOKE ALL ON FUNCTION public.guard_import_provenance() FROM PUBLIC;
CREATE TRIGGER documents_import_provenance BEFORE UPDATE OF import_package_id ON public.documents
 FOR EACH ROW EXECUTE FUNCTION public.guard_import_provenance();
-- Defense in depth: all application readers, including direct historical evidence,
-- are fenced at the database. Worker readers additionally require ready versions.
CREATE POLICY import_gate ON public.documents AS RESTRICTIVE TO flare_app USING (
 import_package_id IS NULL OR EXISTS(SELECT 1 FROM public.import_packages p
 WHERE (p.workspace_id,p.id)=(documents.workspace_id,documents.import_package_id)
 AND p.status IN ('completed','completed_with_skips')));
CREATE POLICY import_gate ON public.document_versions AS RESTRICTIVE TO flare_app USING (
 EXISTS(SELECT 1 FROM public.documents d WHERE (d.workspace_id,d.id)=(document_versions.workspace_id,document_versions.document_id)));
CREATE POLICY import_gate ON public.chunks AS RESTRICTIVE TO flare_app USING (
 EXISTS(SELECT 1 FROM public.document_versions v WHERE (v.workspace_id,v.id)=(chunks.workspace_id,chunks.document_version_id)));

CREATE FUNCTION public.import_api(p_action text,p_id uuid,p_payload jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
 u text:=nullif(current_setting('app.user_id',true),''); p public.import_packages; q public.import_packages;
 t uuid; k text; pol jsonb; sz bigint; used bigint;
BEGIN
 -- Auth and membership locks serialize revoke against a write/gate transaction.
 PERFORM id FROM public.auth_users WHERE id=u AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 PERFORM user_id FROM public.workspace_members WHERE workspace_id=w AND user_id=u AND role IN ('owner','editor') FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','forbidden'); END IF;
 PERFORM id FROM public.workspaces WHERE id=w FOR UPDATE;
 IF p_action='create' THEN
  SELECT * INTO p FROM public.import_packages WHERE workspace_id=w AND request_key=(p_payload->>'requestKey')::uuid;
  IF FOUND THEN RETURN jsonb_build_object('id',p.id); END IF;
  pol:=p_payload->'policy'; sz:=(p_payload->>'fileSize')::bigint;
  IF sz<=0 OR sz>(pol->>'compressed_bytes')::bigint THEN RETURN jsonb_build_object('error','compressed_bytes'); END IF;
  IF (SELECT count(*) FROM public.import_packages WHERE workspace_id=w AND expires_at>clock_timestamp() AND status IN ('uploading','staged','queued','processing','retry_wait')) >= (pol->>'workspace_concurrency')::int THEN RETURN jsonb_build_object('error','concurrency_limit'); END IF;
  SELECT coalesce(sum(bytes),0) INTO used FROM public.import_objects WHERE workspace_id=w AND status<>'deleted';
  -- Unstarted sessions also reserve staging capacity.
  used:=used+coalesce((SELECT sum(file_size) FROM public.import_packages WHERE workspace_id=w AND status='uploading' AND expires_at>clock_timestamp() AND object_key IS NULL),0);
  IF used+sz>(pol->>'staged_quota_bytes')::bigint THEN RETURN jsonb_build_object('error','staged_quota'); END IF;
  INSERT INTO public.import_packages(workspace_id,requested_by_user_id,source_kind,file_name,file_size,request_key,policy,expires_at)
   VALUES(w,u,p_payload->>'sourceKind',p_payload->>'fileName',sz,(p_payload->>'requestKey')::uuid,pol,clock_timestamp()+make_interval(secs=>(pol->>'staging_seconds')::int)) RETURNING * INTO p;
  RETURN jsonb_build_object('id',p.id);
 END IF;
 SELECT * INTO p FROM public.import_packages WHERE workspace_id=w AND id=p_id FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF p_action='cancel' THEN
  IF p.status IN ('completed','completed_with_skips','duplicate') THEN RETURN jsonb_build_object('error','already_published'); END IF;
  UPDATE public.import_packages SET status='cancelled',generation=generation+1,lease_token=NULL,upload_token=NULL,reserved_bytes=0,completed_at=clock_timestamp(),retryable=false WHERE id=p.id;
  UPDATE public.import_objects SET expires_at=clock_timestamp() WHERE package_id=p.id AND status='sealed';
 ELSIF p_action='upload_claim' THEN
  IF p.status<>'uploading' OR p.expires_at<=clock_timestamp() OR (p.upload_token IS NOT NULL AND p.upload_expires_at>clock_timestamp()) THEN RETURN jsonb_build_object('error','invalid_state'); END IF;
  -- Immutable per-attempt object key; old late writers never reuse a cleaned key.
  SELECT coalesce(sum(bytes),0) INTO used FROM public.import_objects WHERE workspace_id=w AND status<>'deleted';
  used:=used+coalesce((SELECT sum(file_size) FROM public.import_packages WHERE workspace_id=w AND status='uploading' AND expires_at>clock_timestamp() AND object_key IS NULL AND id<>p.id),0);
  IF used+p.file_size>(p.policy->>'staged_quota_bytes')::bigint THEN RETURN jsonb_build_object('error','staged_quota'); END IF;
  t:=gen_random_uuid(); k:=replace(p.id::text,'-','')||'-'||replace(t::text,'-','');
  INSERT INTO public.import_objects(key,workspace_id,package_id,bytes,expires_at) VALUES(k,w,p.id,p.file_size,clock_timestamp()+make_interval(secs=>(p.policy->>'upload_seconds')::int));
  UPDATE public.import_packages SET object_key=k,upload_token=t,upload_expires_at=clock_timestamp()+make_interval(secs=>(p.policy->>'upload_seconds')::int) WHERE id=p.id;
  RETURN jsonb_build_object('id',p.id,'key',k,'token',t,'policy',p.policy,'fileSize',p.file_size);
 ELSIF p_action='upload_done' THEN
  IF p.status<>'uploading' OR p.upload_token IS DISTINCT FROM (p_payload->>'token')::uuid OR p.upload_expires_at<=clock_timestamp() OR (p_payload->>'bytes')::bigint<>p.file_size OR p_payload->>'hash' !~ '^[0-9a-f]{64}$' THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
  UPDATE public.import_objects SET status='sealed',expires_at=p.expires_at WHERE key=p.object_key AND status='writing';
  IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
  UPDATE public.import_packages SET status='staged',archive_hash=p_payload->>'hash',upload_token=NULL WHERE id=p.id;
 ELSIF p_action='upload_abort' THEN
  IF p.upload_token=(p_payload->>'token')::uuid THEN UPDATE public.import_packages SET status='failed',error_code='upload_failed',upload_token=NULL,completed_at=clock_timestamp() WHERE id=p.id; END IF;
 ELSIF p_action='finalize' THEN
  IF p.status='duplicate' THEN RETURN jsonb_build_object('id',p.canonical_id); END IF;
  IF p.status IN ('queued','processing','retry_wait','completed','completed_with_skips') THEN RETURN jsonb_build_object('id',p.id); END IF;
  IF p.status<>'staged' OR p.expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('error','invalid_state'); END IF;
  SELECT * INTO q FROM public.import_packages WHERE workspace_id=w AND source_kind=p.source_kind AND archive_hash=p.archive_hash AND id<>p.id AND status IN ('queued','processing','retry_wait','completed','completed_with_skips');
  IF FOUND THEN
   UPDATE public.import_packages SET status='duplicate',canonical_id=q.id,completed_at=clock_timestamp() WHERE id=p.id;
   RETURN jsonb_build_object('id',q.id);
  END IF;
  UPDATE public.import_packages SET status='queued',phase='inspect',job_deadline=clock_timestamp()+make_interval(secs=>(p.policy->>'job_seconds')::int) WHERE id=p.id;
 ELSIF p_action='retry' THEN
  IF p.status<>'failed' OR NOT p.retryable OR p.attempts>=(p.policy->>'attempts')::int OR p.expires_at<=clock_timestamp() OR NOT EXISTS(SELECT 1 FROM public.import_objects WHERE key=p.object_key AND status='sealed') THEN RETURN jsonb_build_object('error','not_retryable'); END IF;
  UPDATE public.import_packages SET status='retry_wait',available_at=clock_timestamp(),error_code=NULL,job_deadline=clock_timestamp()+make_interval(secs=>(p.policy->>'job_seconds')::int) WHERE id=p.id;
 ELSE RETURN jsonb_build_object('error','invalid_action'); END IF;
 RETURN jsonb_build_object('id',p.id);
END $$;

CREATE FUNCTION public.claim_import_package(p_global int) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ DECLARE p public.import_packages; BEGIN
 IF p_global<1 THEN RAISE EXCEPTION 'Invalid bounds'; END IF;
 PERFORM pg_advisory_xact_lock(1919001);
 IF (SELECT count(*) FROM public.import_packages WHERE status='processing' AND lease_expires_at>clock_timestamp())>=p_global THEN RETURN NULL; END IF;
 SELECT * INTO p FROM public.import_packages WHERE status IN ('queued','retry_wait','processing') AND available_at<=clock_timestamp()
 AND (lease_expires_at IS NULL OR lease_expires_at<=clock_timestamp()) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF p.attempts>=(p.policy->>'attempts')::int OR p.expires_at<=clock_timestamp() OR p.job_deadline<=clock_timestamp() THEN
 UPDATE public.import_packages SET status='failed',error_code='attempts_or_deadline',reserved_bytes=0,retryable=false,completed_at=clock_timestamp(),generation=generation+1 WHERE id=p.id;
 RETURN jsonb_build_object('expired',true); END IF;
 UPDATE public.import_packages SET status='processing',attempts=attempts+1,generation=generation+1,lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+make_interval(secs=>(p.policy->>'lease_seconds')::int) WHERE id=p.id RETURNING * INTO p;
 RETURN to_jsonb(p);
END $$;

CREATE FUNCTION public.import_worker_step(p_id uuid,p_token uuid,p_generation bigint,p_action text,p_data jsonb)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.import_packages; e public.import_package_entries; row jsonb; c jsonb; did uuid; vid uuid; meta jsonb;
 n int; b bigint; used bigint; title text;
BEGIN
 SELECT * INTO p FROM public.import_packages WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR p.status<>'processing' OR p.lease_token IS DISTINCT FROM p_token OR p.generation<>p_generation OR p.lease_expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
 PERFORM set_config('app.workspace_id',p.workspace_id::text,true); PERFORM set_config('app.user_id',p.requested_by_user_id,true);
 PERFORM id FROM public.auth_users WHERE id=p.requested_by_user_id AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN p_action:='reject'; p_data:=jsonb_build_object('code','authorization_revoked'); END IF;
 PERFORM user_id FROM public.workspace_members WHERE workspace_id=p.workspace_id AND user_id=p.requested_by_user_id AND role IN ('owner','editor') FOR SHARE;
 IF NOT FOUND THEN p_action:='reject'; p_data:=jsonb_build_object('code','authorization_revoked'); END IF;
 IF p.job_deadline<=clock_timestamp() OR p.expires_at<=clock_timestamp() THEN p_action:='reject'; p_data:=jsonb_build_object('code','job_deadline'); END IF;
 IF p_action='heartbeat' THEN
 UPDATE public.import_packages SET lease_expires_at=clock_timestamp()+make_interval(secs=>(p.policy->>'lease_seconds')::int) WHERE id=p.id;
 ELSIF p_action IN ('reject','transient') THEN
 UPDATE public.import_packages SET status=CASE WHEN p_action='transient' AND attempts<(policy->>'attempts')::int THEN 'retry_wait' ELSE 'failed' END,
 error_code=p_data->>'code',retryable=(p_action='transient'),lease_token=NULL,lease_expires_at=NULL,
 available_at=clock_timestamp()+make_interval(secs=>(p.policy->>'backoff_seconds')::int*p.attempts),completed_at=clock_timestamp(),reserved_bytes=CASE WHEN p_action='reject' THEN 0 ELSE reserved_bytes END WHERE id=p.id;
 RETURN jsonb_build_object('error',p_data->>'code');
 ELSIF p_action='manifest' THEN
  IF p.entry_count IS NOT NULL THEN RETURN jsonb_build_object('ok',true); END IF;
  IF jsonb_array_length(p_data)>(p.policy->>'entries')::int OR octet_length(p_data::text)>(p.policy->>'manifest_bytes')::int THEN RETURN jsonb_build_object('error','manifest_bound'); END IF;
  FOR row IN SELECT value FROM jsonb_array_elements(p_data) LOOP
   INSERT INTO public.import_package_entries(workspace_id,package_id,ordinal,path,canonical_path,file_bytes,skip_reason)
   VALUES(p.workspace_id,p.id,(row->>'ordinal')::int,row->>'path',row->>'canonicalPath',(row->>'fileBytes')::bigint,row->>'skipReason');
  END LOOP;
  UPDATE public.import_packages SET entry_count=jsonb_array_length(p_data),phase='parse' WHERE id=p.id;
 ELSIF p_action='next' THEN
  SELECT * INTO e FROM public.import_package_entries WHERE package_id=p.id AND status='pending' ORDER BY ordinal LIMIT 1;
  IF FOUND THEN RETURN jsonb_build_object('entry',to_jsonb(e)); END IF;
  SELECT * INTO e FROM public.import_package_entries WHERE package_id=p.id AND status='prepared' ORDER BY ordinal LIMIT 1;
  IF FOUND THEN RETURN jsonb_build_object('publish',e.ordinal); END IF;
  RETURN jsonb_build_object('gate',true);
 ELSIF p_action='entry' THEN
  SELECT * INTO e FROM public.import_package_entries WHERE package_id=p.id AND ordinal=(p_data->>'ordinal')::int FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('error','invalid_entry'); END IF;
  IF e.status<>'pending' THEN RETURN jsonb_build_object('ok',true); END IF;
  row:=p_data->'parsed'; n:=jsonb_array_length(row->'chunks');
  IF n>(p.policy->>'chunks_file')::int OR p.chunk_count+n>(p.policy->>'chunks_package')::int THEN RETURN jsonb_build_object('error','chunk_bound'); END IF;
  SELECT coalesce(sum(octet_length(value->>'content')),0) INTO b FROM jsonb_array_elements(row->'chunks');
  IF b>(p.policy->>'expanded_bytes')::bigint OR EXISTS(SELECT 1 FROM jsonb_array_elements(row->'chunks') WHERE octet_length(value->>'content')>(p.policy->>'chunk_bytes')::int) THEN RETURN jsonb_build_object('error','chunk_bound'); END IF;
  PERFORM id FROM public.workspaces WHERE id=p.workspace_id FOR UPDATE;
  SELECT coalesce(sum(octet_length(content)),0) INTO used FROM public.chunks WHERE workspace_id=p.workspace_id;
  used:=used+coalesce((SELECT sum(reserved_bytes) FROM public.import_packages WHERE workspace_id=p.workspace_id AND status IN ('processing','queued','retry_wait')),0);
  IF used+b>(p.policy->>'source_quota_bytes')::bigint THEN RETURN jsonb_build_object('error','source_quota'); END IF;
  UPDATE public.import_package_entries SET status=row->>'status',parsed=row,file_hash=p_data->>'hash' WHERE package_id=p.id AND ordinal=e.ordinal;
  UPDATE public.import_packages SET prepared_count=prepared_count+CASE WHEN row->>'status'='prepared' THEN 1 ELSE 0 END,skipped_count=skipped_count+CASE WHEN row->>'status'='skipped' THEN 1 ELSE 0 END,chunk_count=chunk_count+n,reserved_bytes=reserved_bytes+b WHERE id=p.id;
 ELSIF p_action='publish' THEN
  SELECT * INTO e FROM public.import_package_entries WHERE package_id=p.id AND ordinal=(p_data->>'ordinal')::int FOR UPDATE;
  IF NOT FOUND OR e.status NOT IN ('prepared','published') THEN RETURN jsonb_build_object('error','invalid_entry'); END IF;
  IF e.status='published' THEN RETURN jsonb_build_object('ok',true); END IF;
  did:=gen_random_uuid(); vid:=gen_random_uuid();
  title:=regexp_replace(regexp_replace(e.path,'^.*/',''),'\.[^.]*$',''); IF btrim(title)='' THEN title:='Imported source'; END IF;
  meta:=jsonb_build_object('fileName',regexp_replace(e.path,'^.*/',''),'fileSize',e.file_bytes,'importPackageId',p.id,'relativePath',e.path,'sourceKind',p.source_kind,'fileHash',e.file_hash);
  INSERT INTO public.documents(id,workspace_id,title,source_type,metadata,import_package_id) VALUES(did,p.workspace_id,title,'file',meta,p.id);
  INSERT INTO public.document_versions(id,workspace_id,document_id,version_number,content_hash,parser_version,snapshot_title,snapshot_metadata,state)
   VALUES(vid,p.workspace_id,did,1,e.parsed->>'contentHash','zip-v1-'||(e.parsed->>'format'),title,meta,'processing');
  n:=0; b:=0;
  FOR c IN SELECT value FROM jsonb_array_elements(e.parsed->'chunks') LOOP
   INSERT INTO public.chunks(workspace_id,document_version_id,ordinal,content,locator) VALUES(p.workspace_id,vid,n,c->>'content',c->'locator');
   n:=n+1; b:=b+octet_length(c->>'content');
  END LOOP;
  UPDATE public.import_package_entries SET status='published',document_id=did,version_id=vid,parsed=NULL WHERE package_id=p.id AND ordinal=e.ordinal;
  UPDATE public.import_packages SET phase='publish',published_count=published_count+1,reserved_bytes=reserved_bytes-b WHERE id=p.id;
 ELSIF p_action='gate' THEN
  IF p.entry_count IS NULL OR p.prepared_count=0 OR p.published_count<>p.prepared_count OR EXISTS(SELECT 1 FROM public.import_package_entries WHERE package_id=p.id AND status NOT IN ('published','skipped')) THEN RETURN jsonb_build_object('error','no_supported_content_or_incomplete'); END IF;
  UPDATE public.document_versions v SET state='ready' FROM public.import_package_entries e WHERE e.package_id=p.id AND (v.workspace_id,v.id)=(e.workspace_id,e.version_id);
  UPDATE public.documents d SET current_version_id=e.version_id FROM public.import_package_entries e WHERE e.package_id=p.id AND (d.workspace_id,d.id)=(e.workspace_id,e.document_id);
  UPDATE public.import_packages SET status=CASE WHEN skipped_count>0 THEN 'completed_with_skips' ELSE 'completed' END,phase='complete',completed_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL,retryable=false,reserved_bytes=0 WHERE id=p.id;
  UPDATE public.import_objects SET expires_at=clock_timestamp() WHERE package_id=p.id AND status='sealed';
  INSERT INTO public.import_publications(workspace_id,package_id,requested_by_user_id,source_kind,source_count,chunk_count) VALUES(p.workspace_id,p.id,p.requested_by_user_id,p.source_kind,p.published_count,p.chunk_count) ON CONFLICT(package_id) DO NOTHING;
 ELSE RETURN jsonb_build_object('error','invalid_action'); END IF;
 RETURN jsonb_build_object('ok',true);
END $$;

CREATE FUNCTION public.import_cleanup(p_key text,p_token uuid,p_action text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.import_objects; p public.import_packages; BEGIN
 IF p_action='claim' THEN
  SELECT obj.* INTO o FROM public.import_objects obj JOIN public.import_packages pkg ON pkg.id=obj.package_id
   WHERE obj.status<>'deleted' AND obj.available_at<=clock_timestamp()
   AND (obj.cleanup_expires_at IS NULL OR obj.cleanup_expires_at<=clock_timestamp())
   AND (pkg.status IN ('completed','completed_with_skips','cancelled','expired','duplicate')
      OR (pkg.status='failed' AND (NOT pkg.retryable OR pkg.expires_at<=clock_timestamp()))
      OR obj.key IS DISTINCT FROM pkg.object_key
      OR (pkg.expires_at<=clock_timestamp() AND coalesce(pkg.lease_expires_at,'-infinity')<=clock_timestamp()))
   -- Never delete a still-running upload attempt, including a cancelled one.
   AND (obj.expires_at<=clock_timestamp() OR (obj.status='sealed' AND pkg.status IN ('completed','completed_with_skips','cancelled','duplicate')))
   ORDER BY obj.available_at FOR UPDATE OF obj SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT * INTO p FROM public.import_packages WHERE id=o.package_id FOR UPDATE;
  IF p.expires_at<=clock_timestamp() AND p.status IN ('uploading','staged','queued','processing','retry_wait','failed') THEN
   UPDATE public.import_packages SET status='expired',generation=generation+1,lease_token=NULL,upload_token=NULL,reserved_bytes=0,retryable=false WHERE id=p.id;
   p.status:='expired';
  END IF;
  -- Current attempt is sealed and terminal: due now after the gate; writing
  -- attempts stay quarantined through their deadline to fence late writers.
  UPDATE public.import_objects SET status='deleting',cleanup_token=gen_random_uuid(),cleanup_expires_at=clock_timestamp()+make_interval(secs=>(p.policy->>'lease_seconds')::int),attempts=attempts+1,
    overdue=clock_timestamp()>expires_at+make_interval(secs=>(p.policy->>'cleanup_seconds')::int) WHERE key=o.key RETURNING * INTO o;
  PERFORM set_config('app.workspace_id',p.workspace_id::text,true); PERFORM set_config('app.user_id',p.requested_by_user_id,true);
  IF p.status IN ('failed','cancelled','expired','duplicate') AND (NOT p.retryable OR p.expires_at<=clock_timestamp()) THEN
   -- Only this private function owner may use this cleanup branch of RLS.
   PERFORM set_config('app.import_cleanup','true',true);
   UPDATE public.import_package_entries SET document_id=NULL,version_id=NULL,parsed=NULL WHERE package_id=p.id;
   DELETE FROM public.documents WHERE import_package_id=p.id AND current_version_id IS NULL;
  END IF;
  RETURN to_jsonb(o);
 END IF;
 SELECT * INTO o FROM public.import_objects WHERE key=p_key FOR UPDATE;
 IF NOT FOUND OR o.status<>'deleting' OR o.cleanup_token IS DISTINCT FROM p_token OR o.cleanup_expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
 SELECT * INTO p FROM public.import_packages WHERE id=o.package_id;
 IF p_action='check' THEN RETURN jsonb_build_object('ok',true);
 ELSIF p_action='done' THEN UPDATE public.import_objects SET status='deleted',cleanup_token=NULL,cleanup_expires_at=NULL WHERE key=o.key;
 ELSIF p_action='retry' THEN UPDATE public.import_objects SET cleanup_token=NULL,cleanup_expires_at=NULL,available_at=clock_timestamp()+make_interval(secs=>(p.policy->>'backoff_seconds')::int*least(o.attempts,100)) WHERE key=o.key;
 ELSE RETURN jsonb_build_object('error','invalid_action'); END IF;
 RETURN jsonb_build_object('ok',true);
END $$;
