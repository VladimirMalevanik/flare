-- OPS-005 bounded, temporary ZIP bytes. Object rows are permanent retirement fences.
ALTER TABLE public.import_objects ADD COLUMN storage_admitted_at timestamptz;
ALTER TABLE public.import_objects ADD COLUMN storage_bytes bigint NOT NULL DEFAULT 0 CHECK(storage_bytes>=0 AND storage_bytes<=bytes);
ALTER TABLE public.import_objects ADD COLUMN storage_blocks integer NOT NULL DEFAULT 0 CHECK(storage_blocks BETWEEN 0 AND 32);
CREATE INDEX import_storage_admissions ON public.import_objects(storage_admitted_at) WHERE storage_admitted_at IS NOT NULL;
CREATE INDEX import_package_creation_rate ON public.import_packages(workspace_id,created_at);
CREATE TABLE public.import_staging_blocks (
 key text NOT NULL REFERENCES public.import_objects(key), ordinal integer NOT NULL CHECK(ordinal BETWEEN 0 AND 31),
 data bytea NOT NULL CHECK(octet_length(data) BETWEEN 1 AND 262144), PRIMARY KEY(key,ordinal)
);
CREATE TABLE public.import_staging_health (
 mode text PRIMARY KEY CHECK(mode IN ('jobs','cleanup')), touched_at timestamptz NOT NULL
);

CREATE FUNCTION public._import_staging_upload_guard(k text,t uuid) RETURNS public.import_objects
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.import_packages; o public.import_objects;
 w uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
 u text:=nullif(current_setting('app.user_id',true),'');
BEGIN
 IF session_user<>'flare_app' OR w IS NULL OR u IS NULL OR t IS NULL THEN RAISE EXCEPTION 'forbidden'; END IF;
 PERFORM id FROM public.auth_users WHERE id=u AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'forbidden'; END IF;
 PERFORM user_id FROM public.workspace_members WHERE workspace_id=w AND user_id=u AND role IN ('owner','editor') FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'forbidden'; END IF;
 PERFORM id FROM public.workspaces WHERE id=w FOR UPDATE;
 SELECT p0.* INTO p FROM public.import_packages p0 JOIN public.import_objects o0 ON o0.package_id=p0.id
  WHERE o0.key=k AND p0.workspace_id=w FOR UPDATE OF p0;
 IF NOT FOUND OR p.status<>'uploading' OR p.object_key IS DISTINCT FROM k OR p.upload_token IS DISTINCT FROM t
  OR p.upload_expires_at IS NULL OR p.upload_expires_at<=clock_timestamp() OR p.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'lease_lost'; END IF;
 SELECT * INTO o FROM public.import_objects WHERE key=k FOR UPDATE;
 IF o.status<>'writing' OR o.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'lease_lost'; END IF;
 RETURN o;
END $$;

CREATE FUNCTION public.import_staging_upload(k text,t uuid,action text,n integer,payload bytea) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.import_objects; previous bytea; length integer;
BEGIN
 -- Serialize admission before taking tenant/package/object locks. Payload writes
 -- do not hold this global lock and cannot increase their declared reservation.
 IF action='begin' THEN PERFORM pg_advisory_xact_lock(1919222); END IF;
 o:=public._import_staging_upload_guard(k,t);
 IF o.bytes>8388608 THEN RAISE EXCEPTION 'compressed_bytes'; END IF;
 IF action='begin' THEN
  IF o.storage_admitted_at IS NULL THEN
   IF (SELECT coalesce(sum(bytes),0) FROM public.import_objects WHERE status<>'deleted')>67108864 THEN RAISE EXCEPTION 'staged_quota'; END IF;
   IF (SELECT coalesce(sum(bytes),0) FROM public.import_objects WHERE storage_admitted_at>clock_timestamp()-interval '1 hour')+o.bytes>134217728 THEN RAISE EXCEPTION 'staged_quota'; END IF;
   IF (SELECT count(*) FROM public.import_objects WHERE storage_admitted_at>clock_timestamp()-interval '1 hour')>=128 THEN RAISE EXCEPTION 'staged_quota'; END IF;
   UPDATE public.import_objects SET storage_admitted_at=clock_timestamp() WHERE key=k;
  END IF;
  IF o.storage_blocks<>0 THEN RAISE EXCEPTION 'object_exists'; END IF;
  RETURN jsonb_build_object('bytes',o.bytes);
 END IF;
 IF o.storage_admitted_at IS NULL THEN RAISE EXCEPTION 'lease_lost'; END IF;
 IF action='append' THEN
  length:=octet_length(payload);
  IF length IS NULL OR length NOT BETWEEN 1 AND 262144 OR n IS NULL OR n NOT BETWEEN 0 AND 31 THEN RAISE EXCEPTION 'compressed_bytes'; END IF;
  IF n<o.storage_blocks THEN
   SELECT data INTO previous FROM public.import_staging_blocks WHERE key=k AND ordinal=n;
   IF previous IS DISTINCT FROM payload THEN RAISE EXCEPTION 'integrity_failure'; END IF;
   RETURN jsonb_build_object('bytes',o.storage_bytes);
  END IF;
  IF n<>o.storage_blocks OR o.storage_bytes+length>o.bytes
   OR (length<>262144 AND o.storage_bytes+length<>o.bytes) THEN RAISE EXCEPTION 'integrity_failure'; END IF;
  INSERT INTO public.import_staging_blocks(key,ordinal,data) VALUES(k,n,payload);
  UPDATE public.import_objects SET storage_bytes=storage_bytes+length,storage_blocks=storage_blocks+1 WHERE key=k;
  RETURN jsonb_build_object('bytes',o.storage_bytes+length);
 ELSIF action='finish' THEN
  IF o.storage_bytes<>o.bytes THEN RAISE EXCEPTION 'integrity_failure'; END IF;
  RETURN jsonb_build_object('bytes',o.storage_bytes);
 END IF;
 RAISE EXCEPTION 'invalid_action';
END $$;

CREATE FUNCTION public._import_staging_job_guard(k text,j uuid,t uuid,g bigint) RETURNS public.import_objects
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.import_packages; o public.import_objects;
BEGIN
 IF session_user<>'flare_worker' OR j IS NULL OR t IS NULL OR g IS NULL THEN RAISE EXCEPTION 'forbidden'; END IF;
 SELECT * INTO p FROM public.import_packages WHERE id=j FOR SHARE;
 IF NOT FOUND OR p.status<>'processing' OR p.object_key IS DISTINCT FROM k OR p.lease_token IS DISTINCT FROM t
  OR p.generation IS DISTINCT FROM g OR p.lease_expires_at IS NULL OR p.lease_expires_at<=clock_timestamp()
  OR p.job_deadline IS NULL OR p.job_deadline<=clock_timestamp() OR p.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'lease_lost'; END IF;
 PERFORM set_config('app.user_id',p.requested_by_user_id,true);
 PERFORM set_config('app.workspace_id',p.workspace_id::text,true);
 PERFORM id FROM public.auth_users WHERE id=p.requested_by_user_id AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'authorization_revoked'; END IF;
 PERFORM user_id FROM public.workspace_members WHERE workspace_id=p.workspace_id AND user_id=p.requested_by_user_id AND role IN ('owner','editor') FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'authorization_revoked'; END IF;
 SELECT * INTO o FROM public.import_objects WHERE key=k FOR SHARE;
 IF NOT FOUND OR o.package_id<>j OR o.status<>'sealed' OR o.storage_admitted_at IS NULL
  OR o.storage_bytes<>o.bytes OR o.bytes>8388608 THEN RAISE EXCEPTION 'lease_lost'; END IF;
 RETURN o;
END $$;

CREATE FUNCTION public.import_staging_size(k text,j uuid,t uuid,g bigint) RETURNS bigint
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.import_objects;
BEGIN o:=public._import_staging_job_guard(k,j,t,g); RETURN o.storage_bytes; END $$;

CREATE FUNCTION public.import_staging_read(k text,j uuid,t uuid,g bigint,n integer) RETURNS bytea
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.import_objects; payload bytea;
BEGIN
 o:=public._import_staging_job_guard(k,j,t,g);
 IF n IS NULL OR n<0 OR n>32 THEN RAISE EXCEPTION 'integrity_failure'; END IF;
 IF n=o.storage_blocks THEN RETURN NULL; END IF;
 IF n>o.storage_blocks THEN RAISE EXCEPTION 'integrity_failure'; END IF;
 SELECT data INTO payload FROM public.import_staging_blocks WHERE key=k AND ordinal=n;
 IF NOT FOUND THEN RAISE EXCEPTION 'integrity_failure'; END IF;
 RETURN payload;
END $$;

CREATE FUNCTION public.import_staging_retire(k text,t uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.import_objects;
BEGIN
 IF session_user<>'flare_worker' OR t IS NULL THEN RAISE EXCEPTION 'forbidden'; END IF;
 SELECT * INTO o FROM public.import_objects WHERE key=k FOR UPDATE;
 IF NOT FOUND OR o.status<>'deleting' OR o.cleanup_token IS DISTINCT FROM t OR o.cleanup_expires_at IS NULL OR o.cleanup_expires_at<=clock_timestamp()
  THEN RAISE EXCEPTION 'lease_lost'; END IF;
 DELETE FROM public.import_staging_blocks WHERE key=k;
 UPDATE public.import_objects SET storage_bytes=0,storage_blocks=0 WHERE key=k;
END $$;

CREATE FUNCTION public.guard_import_staging_seal() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.status='sealed' AND OLD.status='writing' AND NEW.storage_admitted_at IS NOT NULL AND NEW.storage_bytes<>NEW.bytes
  THEN RAISE EXCEPTION 'integrity_failure'; END IF;
 -- Existing cleanup completion cannot retire metadata while bytes remain. The
 -- original cleanup capability and LocalStagedObjects behavior stay unchanged.
 IF NEW.status='deleted' AND NEW.storage_admitted_at IS NOT NULL AND
  (NEW.storage_bytes<>0 OR NEW.storage_blocks<>0 OR EXISTS(SELECT 1 FROM public.import_staging_blocks WHERE key=NEW.key))
  THEN RAISE EXCEPTION 'integrity_failure'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER import_staging_seal BEFORE UPDATE OF status ON public.import_objects
 FOR EACH ROW EXECUTE FUNCTION public.guard_import_staging_seal();

CREATE FUNCTION public.guard_import_staging_package_rate() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 -- import_api holds the workspace row lock before this INSERT; use no global
 -- admission lock here, preserving the workspace/admission lock order.
 IF (SELECT count(*) FROM public.import_packages WHERE workspace_id=NEW.workspace_id
     AND created_at>clock_timestamp()-interval '1 hour')>=120 THEN RAISE EXCEPTION 'concurrency_limit'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER import_staging_package_rate BEFORE INSERT ON public.import_packages
 FOR EACH ROW EXECUTE FUNCTION public.guard_import_staging_package_rate();

CREATE FUNCTION public.import_staging_heartbeat(p_mode text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF session_user<>'flare_worker' OR p_mode IS NULL OR p_mode NOT IN ('jobs','cleanup') THEN RAISE EXCEPTION 'forbidden'; END IF;
 INSERT INTO public.import_staging_health(mode,touched_at) VALUES(p_mode,clock_timestamp())
  ON CONFLICT(mode) DO UPDATE SET touched_at=excluded.touched_at;
END $$;
CREATE FUNCTION public.import_staging_ready() RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF session_user<>'flare_app' THEN RAISE EXCEPTION 'forbidden'; END IF;
 RETURN EXISTS(SELECT 1 FROM public.import_staging_health WHERE mode='jobs' AND touched_at>clock_timestamp()-interval '240 seconds')
  AND EXISTS(SELECT 1 FROM public.import_staging_health WHERE mode='cleanup' AND touched_at>clock_timestamp()-interval '30 seconds');
END $$;
CREATE FUNCTION public.import_staging_probe() RETURNS boolean
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT session_user IN ('flare_app','flare_worker') AND
  (SELECT count(*)=2 FROM pg_class WHERE oid IN ('public.import_staging_blocks'::regclass,'public.import_staging_health'::regclass) AND relrowsecurity AND relforcerowsecurity)
 $$;
