CREATE TABLE public.funnel_facts (
 workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
 actor_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('capture','sync_import','zip_import','analyze','inspection')),
 logical_id uuid NOT NULL, occurred_at timestamptz NOT NULL,
 mode text CHECK(mode IN ('manual','scheduled','unknown')), source_count int NOT NULL CHECK(source_count BETWEEN 0 AND 1000000),
 result_count int NOT NULL CHECK(result_count BETWEEN 0 AND 1000000), revision text NOT NULL DEFAULT 'funnel-v1',
 PRIMARY KEY(workspace_id,kind,logical_id)
);
CREATE INDEX funnel_actor_time ON public.funnel_facts(actor_id,workspace_id,occurred_at,kind);
CREATE FUNCTION public.growth_fact(p_w uuid,p_actor text,p_kind text,p_id uuid,p_at timestamptz,p_mode text,p_sources int,p_results int)
 RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 INSERT INTO public.funnel_facts(workspace_id,actor_id,kind,logical_id,occurred_at,mode,source_count,result_count)
 SELECT p_w,p_actor,p_kind,p_id,p_at,p_mode,p_sources,p_results
 WHERE EXISTS(SELECT 1 FROM public.signup_attribution WHERE user_id=p_actor AND eligibility<>'withdrawn')
 AND NOT EXISTS(SELECT 1 FROM public.growth_workspace_optouts WHERE workspace_id=p_w)
 AND NOT EXISTS(SELECT 1 FROM public.growth_policy p WHERE p.fact_seconds IS NOT NULL
 AND p_at<clock_timestamp()-make_interval(secs=>p.fact_seconds))
 ON CONFLICT DO NOTHING;
$$;
-- Domain commit hooks: each fact rolls back with its source transaction.
CREATE FUNCTION public.growth_committed() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_TABLE_NAME='documents' THEN
  IF OLD.current_version_id IS NULL AND NEW.current_version_id IS NOT NULL AND NEW.import_package_id IS NULL
  AND NOT NEW.metadata ? 'originImportBatchId' THEN
   PERFORM public.growth_fact(NEW.workspace_id,nullif(current_setting('app.user_id',true),''),'capture',NEW.id,clock_timestamp(),'manual',1,1);
  END IF;
 ELSIF TG_TABLE_NAME='import_batches' THEN
  IF NEW.status='completed' AND OLD.status<>'completed' THEN
   PERFORM public.growth_fact(NEW.workspace_id,NEW.requested_by_user_id,'sync_import',NEW.id,NEW.completed_at,'manual',1,NEW.chunk_count);
  END IF;
 ELSE
  PERFORM public.growth_fact(NEW.workspace_id,NEW.requested_by_user_id,'zip_import',NEW.package_id,NEW.published_at,'manual',NEW.source_count,NEW.chunk_count);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER growth_capture AFTER UPDATE OF current_version_id ON public.documents FOR EACH ROW EXECUTE FUNCTION public.growth_committed();
CREATE TRIGGER growth_sync_import AFTER UPDATE OF status ON public.import_batches FOR EACH ROW EXECUTE FUNCTION public.growth_committed();
CREATE TRIGGER growth_zip_import AFTER INSERT ON public.import_publications FOR EACH ROW EXECUTE FUNCTION public.growth_committed();
CREATE FUNCTION public.growth_analyze_fact(p_job uuid) RETURNS void LANGUAGE sql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT public.growth_fact(r.workspace_id,r.requested_by_user_id,'analyze',r.id,
 greatest(j.completed_at,g.completed_at),COALESCE(c.mode,'unknown'),r.selected_chunk_count,COALESCE(cardinality(g.flare_ids),0))
 FROM public.analysis_runs r JOIN public.analysis_jobs j ON j.id=r.analysis_job_id
 JOIN public.flare_generation_runs g ON g.analysis_job_id=j.id AND g.generation_revision=r.generation_revision
 LEFT JOIN public.analysis_cycles c ON c.analysis_run_id=r.id
 WHERE j.id=p_job AND j.status='completed' AND g.status='completed';
$$;
CREATE FUNCTION public.growth_terminal() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF NEW.status='completed' THEN
  IF TG_TABLE_NAME='analysis_jobs' THEN PERFORM public.growth_analyze_fact(NEW.id);
  ELSE PERFORM public.growth_analyze_fact(NEW.analysis_job_id); END IF;
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER growth_analysis AFTER UPDATE OF status ON public.analysis_jobs FOR EACH ROW EXECUTE FUNCTION public.growth_terminal();
CREATE TRIGGER growth_generation AFTER UPDATE OF status ON public.flare_generation_runs FOR EACH ROW EXECUTE FUNCTION public.growth_terminal();
-- Anti-join by logical ID, not sequence high-water: late lower sequence commits remain visible.
CREATE FUNCTION public.growth_reconcile(p_limit int) RETURNS int LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r record; n int:=0;
BEGIN
 IF p_limit NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid batch'; END IF;
 FOR r IN SELECT p.* FROM public.import_publications p JOIN public.signup_attribution a ON a.user_id=p.requested_by_user_id
 WHERE a.eligibility<>'withdrawn' AND NOT EXISTS(SELECT 1 FROM public.growth_workspace_optouts o WHERE o.workspace_id=p.workspace_id)
 AND NOT EXISTS(SELECT 1 FROM public.funnel_facts f WHERE f.workspace_id=p.workspace_id AND f.kind='zip_import' AND f.logical_id=p.package_id)
 ORDER BY p.published_at,p.package_id LIMIT p_limit LOOP
  PERFORM public.growth_fact(r.workspace_id,r.requested_by_user_id,'zip_import',r.package_id,r.published_at,'manual',r.source_count,r.chunk_count); n:=n+1;
 END LOOP;
 RETURN n;
END $$;
ALTER TABLE public.activity_events ADD COLUMN interaction_id uuid;
CREATE UNIQUE INDEX activity_interaction ON public.activity_events(workspace_id,actor_id,interaction_id) WHERE interaction_id IS NOT NULL;
CREATE FUNCTION public.growth_inspection(p_id uuid,p_flare uuid,p_source uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
 uid text:=nullif(current_setting('app.user_id',true),''); inserted uuid;
BEGIN
 IF p_id IS NULL OR uid IS NULL OR NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=wid AND user_id=uid)
 OR NOT EXISTS(SELECT 1 FROM public.insights WHERE workspace_id=wid AND id=p_flare AND flare_type IS NOT NULL)
 OR (p_source IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.insight_sources s JOIN public.chunks c ON c.id=s.chunk_id
 JOIN public.document_versions v ON v.id=c.document_version_id JOIN public.documents d ON d.id=v.document_id
 WHERE s.workspace_id=wid AND s.insight_id=p_flare AND d.id=p_source AND d.deleted_at IS NULL
 AND (d.import_package_id IS NULL OR EXISTS(SELECT 1 FROM public.import_packages p WHERE p.id=d.import_package_id AND p.status IN ('completed','completed_with_skips')))))
 THEN RAISE EXCEPTION 'Unavailable inspection target' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM public.signup_attribution WHERE user_id=uid AND eligibility='withdrawn')
 OR EXISTS(SELECT 1 FROM public.growth_workspace_optouts WHERE workspace_id=wid) THEN RETURN; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(wid::text||uid||'-growth-inspection',0));
 IF (SELECT count(*) FROM public.activity_events WHERE workspace_id=wid AND actor_id=uid AND interaction_id IS NOT NULL
 AND created_at>clock_timestamp()-interval '1 hour')>=600 THEN RETURN; END IF;
 INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type,target_id,metadata,interaction_id)
 VALUES(wid,uid,'flare_viewed','flare',p_flare,jsonb_build_object('source','insights_feed'),p_id)
 ON CONFLICT DO NOTHING RETURNING id INTO inserted;
 IF inserted IS NOT NULL THEN PERFORM public.growth_fact(wid,uid,'inspection',p_id,clock_timestamp(),'manual',0,1); END IF;
END $$;
CREATE FUNCTION public.growth_withdraw(p_workspace boolean) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
 uid text:=nullif(current_setting('app.user_id',true),'');
BEGIN
 IF uid IS NULL OR NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=wid AND user_id=uid) THEN
 RAISE EXCEPTION 'Membership required' USING ERRCODE='42501'; END IF;
 IF p_workspace THEN
  IF NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=wid AND user_id=uid AND role='owner') THEN
   RAISE EXCEPTION 'Owner required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.growth_workspace_optouts VALUES(wid) ON CONFLICT DO NOTHING;
  UPDATE public.signup_attribution SET eligibility='withdrawn',first_touch=NULL,last_touch=NULL,revision=NULL,finalized=true WHERE workspace_id=wid;
  DELETE FROM public.funnel_facts WHERE workspace_id=wid;
  DELETE FROM public.activity_events WHERE workspace_id=wid;
 ELSE
  UPDATE public.signup_attribution SET eligibility='withdrawn',first_touch=NULL,last_touch=NULL,revision=NULL,finalized=true WHERE user_id=uid;
  DELETE FROM public.funnel_facts WHERE actor_id=uid;
  DELETE FROM public.activity_events WHERE actor_id=uid;
 END IF;
END $$;
CREATE FUNCTION public.growth_account_deleted() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 DELETE FROM public.activity_events WHERE actor_id=OLD.id; RETURN OLD;
END $$;
CREATE TRIGGER growth_delete_account BEFORE DELETE ON public.auth_users FOR EACH ROW EXECUTE FUNCTION public.growth_account_deleted();
CREATE FUNCTION public.growth_cleanup(p_limit int) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.growth_policy; visitors int; budgets int; links int; facts int;
BEGIN
 IF p_limit NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid batch'; END IF;
 SELECT * INTO p FROM public.growth_policy;
 WITH x AS(SELECT reference_hash FROM public.acquisition_visitors WHERE expires_at<=clock_timestamp() ORDER BY expires_at LIMIT p_limit)
 DELETE FROM public.acquisition_visitors WHERE reference_hash IN(SELECT reference_hash FROM x); GET DIAGNOSTICS visitors=ROW_COUNT;
 WITH x AS(SELECT bucket FROM public.acquisition_budgets WHERE hour<date_trunc('hour',clock_timestamp()) LIMIT p_limit)
 DELETE FROM public.acquisition_budgets WHERE bucket IN(SELECT bucket FROM x); GET DIAGNOSTICS budgets=ROW_COUNT;
 -- Expired measurement stays withdrawn: reconciliation must not resurrect it.
 WITH x AS(SELECT user_id FROM public.signup_attribution WHERE eligibility<>'withdrawn'
 AND p.linked_seconds IS NOT NULL AND created_at<clock_timestamp()-make_interval(secs=>p.linked_seconds) LIMIT p_limit)
 UPDATE public.signup_attribution SET eligibility='withdrawn',first_touch=NULL,last_touch=NULL,revision=NULL WHERE user_id IN(SELECT user_id FROM x);
 GET DIAGNOSTICS links=ROW_COUNT;
 WITH x AS(SELECT workspace_id,kind,logical_id FROM public.funnel_facts f WHERE
 EXISTS(SELECT 1 FROM public.signup_attribution a WHERE a.user_id=f.actor_id AND a.eligibility='withdrawn')
 OR (p.fact_seconds IS NOT NULL AND occurred_at<clock_timestamp()-make_interval(secs=>p.fact_seconds)) LIMIT p_limit)
 DELETE FROM public.funnel_facts f USING x WHERE (f.workspace_id,f.kind,f.logical_id)=(x.workspace_id,x.kind,x.logical_id);
 GET DIAGNOSTICS facts=ROW_COUNT;
 WITH x AS(SELECT id FROM public.activity_events e WHERE interaction_id IS NOT NULL AND
 (EXISTS(SELECT 1 FROM public.signup_attribution a WHERE a.user_id=e.actor_id AND a.eligibility='withdrawn')
 OR (p.fact_seconds IS NOT NULL AND created_at<clock_timestamp()-make_interval(secs=>p.fact_seconds))) LIMIT p_limit)
 DELETE FROM public.activity_events WHERE id IN(SELECT id FROM x);
 RETURN jsonb_build_object('visitors',visitors,'budgets',budgets,'links',links,'facts',facts);
END $$;
-- No identity or raw campaign rows are returned. Caller supplies an explicit unit/basis.
CREATE FUNCTION public.growth_report(p_since timestamptz,p_until timestamptz,p_unit text,p_basis text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.growth_policy; result jsonb; channels jsonb;
BEGIN
 SELECT * INTO p FROM public.growth_policy;
 IF NOT p.enabled OR p_since IS NULL OR p_until IS NULL OR p_since>=p_until OR p_until>clock_timestamp()
 OR p_until-p_since>make_interval(days=>p.report_window_days) OR p_unit NOT IN ('account','workspace_creator')
 OR p_basis NOT IN ('first','last') THEN RAISE EXCEPTION 'Reporting policy/window required'; END IF;
 WITH cohort AS(SELECT a.*,
 COALESCE((CASE WHEN p_basis='first' THEN first_touch ELSE last_touch END)->>'utm_source','unknown') AS channel
 FROM public.signup_attribution a WHERE a.created_at>=p_since AND a.created_at<p_until AND eligibility<>'withdrawn'),
 milestones AS(SELECT a.*,outcome.at AS outcome_at,analyzed.at AS analyzed_at,inspected.at AS inspected_at,returned.at AS returned_at
 FROM cohort a
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind IN ('capture','sync_import','zip_import') AND mode='manual' AND source_count>0
 AND a.verification IN ('actual','bypassed') AND occurred_at>=COALESCE(a.verified_at,a.created_at) AND occurred_at<p_until) outcome ON true
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind='analyze' AND mode='manual'
 AND occurred_at>=outcome.at AND occurred_at<p_until) analyzed ON true
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind='inspection' AND occurred_at>=analyzed.at AND occurred_at<p_until) inspected ON true
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind IN ('capture','sync_import','zip_import','inspection') AND mode='manual'
 AND (occurred_at AT TIME ZONE 'UTC')::date>(inspected.at AT TIME ZONE 'UTC')::date AND occurred_at<p_until) returned ON true),
 totals AS(SELECT count(*) n,count(*) FILTER(WHERE eligibility='eligible') eligible,
 count(*) FILTER(WHERE verification='actual') verified,count(*) FILTER(WHERE verification='bypassed') bypassed,
 count(*) FILTER(WHERE verification IN ('pending','legacy_unknown')) verification_unknown,
 count(*) FILTER(WHERE outcome_at IS NOT NULL) outcomes,count(*) FILTER(WHERE analyzed_at IS NOT NULL) analyzed,
 count(*) FILTER(WHERE inspected_at IS NOT NULL) inspected,count(*) FILTER(WHERE returned_at IS NOT NULL) returned,
 count(*) FILTER(WHERE created_at::date<(p_until AT TIME ZONE 'UTC')::date) later_day_observable FROM milestones)
 SELECT CASE WHEN n<p.min_cohort THEN jsonb_build_object('suppressed',true) ELSE jsonb_build_object('suppressed',false,
 'accounts',n,'eligible',eligible,'unknown',n-eligible,'actual_verified',verified,'bypassed',bypassed,'verification_unknown',verification_unknown,
 'committed_outcome',outcomes,'manual_analyze',analyzed,'voluntary_inspection',inspected,'later_day_activity',returned,'later_day_observable',later_day_observable) END INTO result FROM totals;
 WITH cohort AS(SELECT COALESCE((CASE WHEN p_basis='first' THEN first_touch ELSE last_touch END)->>'utm_source','unknown') AS channel
 FROM public.signup_attribution WHERE created_at>=p_since AND created_at<p_until AND eligibility<>'withdrawn'),
 grouped AS(SELECT channel,count(*) AS accounts FROM cohort GROUP BY channel)
 SELECT CASE WHEN bool_and(accounts>=p.min_cohort) THEN jsonb_agg(jsonb_build_object('source',channel,'accounts',accounts) ORDER BY channel)
 ELSE NULL END INTO channels FROM grouped;

 RETURN jsonb_build_object('revision','funnel-v1','policy',p.revision,'unit',p_unit,'basis',p_basis,'calendar','UTC-v1',
 'since',p_since,'until',p_until,'generated_at',clock_timestamp(),'coverage_start','migration-0020',
 'freshness','transactional domain hooks; ZIP anti-join reconciliation available','metrics',result,
 'channels',channels,'channels_suppressed',channels IS NULL,'traffic_qualification','opt-in assertion; human/bot/test status unknown',
 'maturity','later_day_observable is a calendar opportunity, no retention rate selected');
END $$;
