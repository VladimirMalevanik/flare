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
-- Writers share this transaction boundary; removers take it exclusively. Keep
-- lock acquisition in a separate VOLATILE statement so subsequent reads use a
-- fresh READ COMMITTED snapshot after a wait. No tenant permission is changed.
CREATE FUNCTION public.growth_observation_allowed(p_w uuid,p_actor text) RETURNS boolean
 LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
 PERFORM pg_advisory_xact_lock_shared(2020,2);
 -- This also protects legacy events when collection is disabled. Locking a
 -- real account avoids raising an FK error for a delayed delivery after delete.
 PERFORM id FROM public.auth_users WHERE id=p_actor FOR KEY SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 RETURN NOT EXISTS(SELECT 1 FROM public.signup_attribution WHERE user_id=p_actor AND eligibility='withdrawn')
 AND NOT EXISTS(SELECT 1 FROM public.growth_workspace_optouts WHERE workspace_id=p_w);
END $$;
CREATE FUNCTION public.growth_fact(p_w uuid,p_actor text,p_kind text,p_id uuid,p_at timestamptz,p_mode text,p_sources int,p_results int)
 RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT public.growth_observation_allowed(p_w,p_actor) THEN RETURN; END IF;
 INSERT INTO public.funnel_facts(workspace_id,actor_id,kind,logical_id,occurred_at,mode,source_count,result_count)
 SELECT p_w,p_actor,p_kind,p_id,p_at,p_mode,p_sources,p_results
 WHERE EXISTS(SELECT 1 FROM public.growth_policy p WHERE p.enabled AND p.fact_seconds>0
 AND p_at>=clock_timestamp()-make_interval(secs=>p.fact_seconds))
 AND EXISTS(SELECT 1 FROM public.auth_users WHERE id=p_actor)
 AND NOT EXISTS(SELECT 1 FROM public.signup_attribution WHERE user_id=p_actor AND eligibility='withdrawn')
 AND NOT EXISTS(SELECT 1 FROM public.growth_workspace_optouts WHERE workspace_id=p_w)
 ON CONFLICT DO NOTHING;
END;
$$;
-- Domain commit hooks: each fact rolls back with its source transaction.
CREATE FUNCTION public.growth_committed() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_TABLE_NAME='documents' THEN
  IF current_setting('app.growth_human_action',true)='capture' AND OLD.current_version_id IS NULL AND NEW.current_version_id IS NOT NULL AND NEW.import_package_id IS NULL
  AND NOT NEW.metadata ? 'originImportBatchId' THEN
   PERFORM public.growth_fact(NEW.workspace_id,nullif(current_setting('app.user_id',true),''),'capture',NEW.id,clock_timestamp(),'manual',1,1);
  END IF;
 ELSIF TG_TABLE_NAME='import_batches' THEN
  IF NEW.status='completed' AND OLD.status<>'completed' THEN
   BEGIN
    LOCK TABLE public.funnel_facts IN ROW EXCLUSIVE MODE NOWAIT;
    PERFORM public.growth_fact(NEW.workspace_id,NEW.requested_by_user_id,'sync_import',NEW.id,NEW.completed_at,'manual',1,NEW.chunk_count);
   EXCEPTION WHEN OTHERS THEN NULL; END;
  END IF;
 ELSE
  -- Import publication is authoritative and replayable. An analytics consumer
  -- never becomes a prerequisite for DATA success. Reconcile missing IDs later.
  BEGIN
   LOCK TABLE public.funnel_facts IN ROW EXCLUSIVE MODE NOWAIT;
   PERFORM public.growth_fact(NEW.workspace_id,NEW.requested_by_user_id,'zip_import',NEW.package_id,NEW.published_at,'manual',NEW.source_count,NEW.chunk_count);
  EXCEPTION WHEN OTHERS THEN NULL; END;
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
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid batch'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.growth_policy WHERE enabled AND fact_seconds>0) THEN RETURN 0; END IF;
 FOR r IN SELECT p.* FROM (
 SELECT workspace_id,package_id AS logical_id,requested_by_user_id,published_at AS occurred_at,
 'zip_import'::text AS kind,source_count,chunk_count FROM public.import_publications
 UNION ALL
 SELECT workspace_id,id,requested_by_user_id,completed_at,'sync_import',1,chunk_count
 FROM public.import_batches WHERE status='completed') p JOIN public.auth_users u ON u.id=p.requested_by_user_id
 WHERE NOT EXISTS(SELECT 1 FROM public.signup_attribution a WHERE a.user_id=u.id AND a.eligibility='withdrawn')
 AND NOT EXISTS(SELECT 1 FROM public.growth_workspace_optouts o WHERE o.workspace_id=p.workspace_id)
 AND NOT EXISTS(SELECT 1 FROM public.growth_policy policy WHERE policy.fact_seconds IS NOT NULL
 AND p.occurred_at<clock_timestamp()-make_interval(secs=>policy.fact_seconds))
 AND NOT EXISTS(SELECT 1 FROM public.funnel_facts f WHERE f.workspace_id=p.workspace_id AND f.kind=p.kind AND f.logical_id=p.logical_id)
 ORDER BY p.occurred_at,p.logical_id LIMIT p_limit LOOP
  PERFORM public.growth_fact(r.workspace_id,r.requested_by_user_id,r.kind,r.logical_id,r.occurred_at,'manual',r.source_count,r.chunk_count); n:=n+1;
 END LOOP;
 RETURN n;
END $$;
ALTER TABLE public.activity_events ADD COLUMN interaction_id uuid;
-- NOT VALID preserves historical legacy actors without an auth row. New events
-- must reference a real account; FK locking/cascade also covers higher-isolation
-- account deletion. Do not scan/rewrite old events or historical migrations.
ALTER TABLE public.activity_events ADD CONSTRAINT growth_activity_actor_fk
 FOREIGN KEY(actor_id) REFERENCES public.auth_users(id) ON DELETE CASCADE NOT VALID;
CREATE UNIQUE INDEX activity_interaction ON public.activity_events(workspace_id,actor_id,interaction_id) WHERE interaction_id IS NOT NULL;
-- Withdrawal and deletion also suppress delayed deliveries through legacy writers.
CREATE FUNCTION public.growth_event_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF NOT public.growth_observation_allowed(NEW.workspace_id,NEW.actor_id) THEN RETURN NULL; END IF;
 -- Narrow interaction observations are growth collection. Existing unrelated
 -- authenticated events keep their domain behavior while collection is off.
 IF NEW.interaction_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.growth_policy WHERE enabled AND fact_seconds>0)
 THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.auth_users WHERE id=NEW.actor_id)
 OR EXISTS(SELECT 1 FROM public.signup_attribution WHERE user_id=NEW.actor_id AND eligibility='withdrawn')
 OR EXISTS(SELECT 1 FROM public.growth_workspace_optouts WHERE workspace_id=NEW.workspace_id) THEN RETURN NULL; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER growth_event_privacy BEFORE INSERT ON public.activity_events FOR EACH ROW EXECUTE FUNCTION public.growth_event_guard();
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
 IF NOT public.growth_observation_allowed(wid,uid) THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.growth_policy WHERE enabled AND fact_seconds>0) THEN RETURN; END IF;
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
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Privacy removal requires READ COMMITTED'; END IF;
 PERFORM pg_advisory_xact_lock(2020,2);
 -- Revalidate authorization after waiting, using a fresh snapshot.
 IF NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=wid AND user_id=uid) THEN
  RAISE EXCEPTION 'Membership required' USING ERRCODE='42501'; END IF;
 IF p_workspace THEN
  IF NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=wid AND user_id=uid AND role='owner') THEN
   RAISE EXCEPTION 'Owner required' USING ERRCODE='42501'; END IF;
  INSERT INTO public.growth_workspace_optouts VALUES(wid) ON CONFLICT DO NOTHING;
  INSERT INTO public.signup_attribution(user_id,workspace_id,created_at,eligibility,finalized)
  SELECT id,initial_workspace_id,created_at,'withdrawn',true FROM public.auth_users WHERE initial_workspace_id=wid
  ON CONFLICT(user_id) DO UPDATE SET eligibility='withdrawn',first_touch=NULL,last_touch=NULL,revision=NULL,finalized=true;
  DELETE FROM public.funnel_facts WHERE workspace_id=wid;
  DELETE FROM public.activity_events WHERE workspace_id=wid;
 ELSE
  INSERT INTO public.signup_attribution(user_id,workspace_id,created_at,eligibility,finalized)
  SELECT id,initial_workspace_id,created_at,'withdrawn',true FROM public.auth_users WHERE id=uid
  ON CONFLICT(user_id) DO UPDATE SET eligibility='withdrawn',first_touch=NULL,last_touch=NULL,revision=NULL,finalized=true;
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
DECLARE p public.growth_policy; visitors int; budgets int; links int; facts int; expired text[]; erased int;
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid batch'; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Privacy removal requires READ COMMITTED'; END IF;
 PERFORM pg_advisory_xact_lock(2020,2);
 SELECT * INTO p FROM public.growth_policy;
 WITH x AS(SELECT reference_hash FROM public.acquisition_visitors WHERE expires_at<=clock_timestamp() ORDER BY expires_at LIMIT p_limit)
 DELETE FROM public.acquisition_visitors WHERE reference_hash IN(SELECT reference_hash FROM x); GET DIAGNOSTICS visitors=ROW_COUNT;
 WITH x AS(SELECT bucket FROM public.acquisition_budgets WHERE hour<date_trunc('hour',clock_timestamp()) LIMIT p_limit)
 DELETE FROM public.acquisition_budgets WHERE bucket IN(SELECT bucket FROM x); GET DIAGNOSTICS budgets=ROW_COUNT;
 -- Expired measurement stays withdrawn: reconciliation must not resurrect it.
 SELECT array_agg(id) INTO expired FROM (SELECT u.id FROM public.auth_users u
 WHERE NOT EXISTS(SELECT 1 FROM public.signup_attribution a WHERE a.user_id=u.id AND a.eligibility='withdrawn')
 AND p.linked_seconds IS NOT NULL AND u.created_at<clock_timestamp()-make_interval(secs=>p.linked_seconds)
 ORDER BY u.created_at,u.id LIMIT p_limit) x;
 INSERT INTO public.signup_attribution(user_id,workspace_id,created_at,eligibility,finalized)
 SELECT id,initial_workspace_id,created_at,'withdrawn',true FROM public.auth_users WHERE id=ANY(expired)
 ON CONFLICT(user_id) DO UPDATE SET eligibility='withdrawn',first_touch=NULL,last_touch=NULL,revision=NULL,finalized=true;
 GET DIAGNOSTICS links=ROW_COUNT;
 -- p_limit bounds expired accounts. Erase each selected account atomically,
 -- including ordinary events; a successful expiry cannot leave linked rows.
 DELETE FROM public.funnel_facts WHERE actor_id=ANY(expired); GET DIAGNOSTICS erased=ROW_COUNT;
 DELETE FROM public.activity_events WHERE actor_id=ANY(expired);
 WITH x AS(SELECT workspace_id,kind,logical_id FROM public.funnel_facts f WHERE
 EXISTS(SELECT 1 FROM public.signup_attribution a WHERE a.user_id=f.actor_id AND a.eligibility='withdrawn')
 OR (p.fact_seconds IS NOT NULL AND occurred_at<clock_timestamp()-make_interval(secs=>p.fact_seconds)) LIMIT p_limit)
 DELETE FROM public.funnel_facts f USING x WHERE (f.workspace_id,f.kind,f.logical_id)=(x.workspace_id,x.kind,x.logical_id);
 GET DIAGNOSTICS facts=ROW_COUNT;
 facts:=facts+erased;
 WITH x AS(SELECT id FROM public.activity_events e WHERE interaction_id IS NOT NULL AND
 (EXISTS(SELECT 1 FROM public.signup_attribution a WHERE a.user_id=e.actor_id AND a.eligibility='withdrawn')
 OR (p.fact_seconds IS NOT NULL AND created_at<clock_timestamp()-make_interval(secs=>p.fact_seconds))) LIMIT p_limit)
 DELETE FROM public.activity_events WHERE id IN(SELECT id FROM x);
 RETURN jsonb_build_object('visitors',visitors,'budgets',budgets,'links',links,'facts',facts);
END $$;
-- Restricted bounded attribution aggregate. No identities or raw references leave this function.
CREATE FUNCTION public.growth_report(p_since timestamptz,p_until timestamptz,p_unit text,p_basis text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.growth_policy; result jsonb; attribution jsonb;
BEGIN
 SELECT * INTO p FROM public.growth_policy;
 IF NOT FOUND OR p.enabled IS DISTINCT FROM true
 OR NOT COALESCE(p.min_cohort BETWEEN 2 AND 1000,false)
 OR NOT COALESCE(p.report_window_days BETWEEN 1 AND 90,false)
 OR p.report_calendar IS DISTINCT FROM 'UTC-v1' OR NOT COALESCE(length(p.revision) BETWEEN 1 AND 80,false)
 OR p.notice_id IS NULL OR p.cleanup_owner IS NULL OR p.eligibility IS DISTINCT FROM 'explicit-opt-in'
 OR NOT COALESCE(p.linked_seconds>0 AND p.fact_seconds>0,false)
 OR p_since IS NULL OR p_until IS NULL OR p_since>=p_until OR p_until>clock_timestamp()
 OR p_until-p_since>make_interval(days=>p.report_window_days) OR p_unit IS NULL OR p_unit NOT IN ('account','workspace_creator')
 OR p_basis IS NULL OR p_basis NOT IN ('first','last') THEN RAISE EXCEPTION 'Reporting policy/window required'; END IF;
 WITH cohort AS(
 SELECT u.id AS user_id,u.initial_workspace_id AS workspace_id,u.created_at,
 u.verification_provenance AS verification,u.email_verified_at AS verified_at,
 COALESCE(a.eligibility,'unknown') AS eligibility,a.user_id IS NOT NULL AS snapshot_present,
 CASE WHEN a.eligibility='eligible' THEN CASE WHEN p_basis='first' THEN a.first_touch ELSE a.last_touch END END AS touch
 FROM public.auth_users u LEFT JOIN public.signup_attribution a ON a.user_id=u.id
 WHERE u.created_at>=p_since AND u.created_at<p_until AND COALESCE(a.eligibility,'unknown')<>'withdrawn'
 AND NOT EXISTS(SELECT 1 FROM public.growth_workspace_optouts o WHERE o.workspace_id=u.initial_workspace_id)),
 dimensions AS(SELECT a.*,
 CASE WHEN NOT snapshot_present THEN 'missing_snapshot' WHEN eligibility<>'eligible' THEN 'unlinked_unknown'
 WHEN NOT COALESCE(touch ?| ARRAY['utm_source','utm_medium','utm_campaign','ref','referrer_domain'],false)
 THEN 'eligible_direct_or_unknown' ELSE 'eligible_non_direct' END AS coverage,
 -- Only the currently approved vocabulary is exportable; retired labels become other.
 CASE WHEN touch ? 'utm_source' THEN CASE WHEN (p.tokens->'utm_source') ? (touch->>'utm_source') THEN touch->>'utm_source' ELSE 'other' END ELSE 'unspecified' END AS source,
 CASE WHEN touch ? 'utm_medium' THEN CASE WHEN (p.tokens->'utm_medium') ? (touch->>'utm_medium') THEN touch->>'utm_medium' ELSE 'other' END ELSE 'unspecified' END AS medium,
 CASE WHEN touch ? 'utm_campaign' THEN CASE WHEN (p.tokens->'utm_campaign') ? (touch->>'utm_campaign') THEN touch->>'utm_campaign' ELSE 'other' END ELSE 'unspecified' END AS campaign,
 CASE WHEN touch ? 'ref' THEN CASE WHEN (p.tokens->'ref') ? (touch->>'ref') THEN touch->>'ref' ELSE 'other' END ELSE 'unspecified' END AS ref,
 CASE WHEN touch ? 'referrer_domain' THEN CASE WHEN (p.tokens->'referrer_domain') ? (touch->>'referrer_domain') THEN touch->>'referrer_domain' ELSE 'other' END ELSE 'unspecified' END AS referrer_domain,
 COALESCE(touch->>'landing_route','unspecified') AS landing_route
 FROM cohort a),
 milestones AS(SELECT a.*,outcome.at AS outcome_at,analyzed.at AS analyzed_at,inspected.at AS inspected_at,returned.at AS returned_at
 FROM dimensions a
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind IN ('capture','sync_import','zip_import') AND mode='manual' AND source_count>0
 AND a.verification IN ('actual','bypassed') AND occurred_at>=COALESCE(a.verified_at,a.created_at) AND occurred_at<p_until) outcome ON true
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind='analyze' AND mode='manual'
 AND occurred_at>=outcome.at AND occurred_at<p_until) analyzed ON true
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind='inspection' AND occurred_at>=analyzed.at AND occurred_at<p_until) inspected ON true
 -- human-return-v1: only explicit foreground inspection observations qualify.
 -- Completion timestamps, including manual-requested ZIP/Analyze, are asynchronous.
 LEFT JOIN LATERAL(SELECT min(occurred_at) AS at FROM public.funnel_facts f WHERE f.actor_id=a.user_id
 AND (p_unit='account' OR f.workspace_id=a.workspace_id) AND kind='inspection' AND mode='manual'
 AND (occurred_at AT TIME ZONE 'UTC')::date>(inspected.at AT TIME ZONE 'UTC')::date AND occurred_at<p_until) returned ON true),
 totals AS(SELECT grouping(coverage) AS total,coverage,source,medium,campaign,ref,referrer_domain,landing_route,
 count(*) n,count(*) FILTER(WHERE eligibility='eligible') eligible,
 count(*) FILTER(WHERE snapshot_present) snapshot_present,count(*) FILTER(WHERE NOT snapshot_present) snapshot_missing,
 count(*) FILTER(WHERE verification='actual' AND verified_at<p_until) verified,count(*) FILTER(WHERE verification='bypassed') bypassed,
 count(*) FILTER(WHERE verification IN ('pending','legacy_unknown') OR (verification='actual' AND (verified_at IS NULL OR verified_at>=p_until))) verification_unknown,
 count(*) FILTER(WHERE outcome_at IS NOT NULL) outcomes,count(*) FILTER(WHERE analyzed_at IS NOT NULL) analyzed,
 count(*) FILTER(WHERE inspected_at IS NOT NULL) inspected,count(*) FILTER(WHERE returned_at IS NOT NULL) returned,
 count(*) FILTER(WHERE (created_at AT TIME ZONE 'UTC')::date<(p_until AT TIME ZONE 'UTC')::date) later_day_observable,
 count(*) FILTER(WHERE (inspected_at AT TIME ZONE 'UTC')::date<(p_until AT TIME ZONE 'UTC')::date) inspection_later_day_observable
 FROM milestones GROUP BY GROUPING SETS((),(coverage,source,medium,campaign,ref,referrer_domain,landing_route))),
 packed AS(SELECT *,CASE WHEN n<p.min_cohort THEN jsonb_build_object('suppressed',true) ELSE jsonb_build_object('suppressed',false,
 'accounts',n,'eligible',eligible,'unknown',n-eligible,'snapshot_present',snapshot_present,'snapshot_missing',snapshot_missing,
 'actual_verified',verified,'bypassed',bypassed,'verification_unknown',verification_unknown,
 'committed_outcome',outcomes,'manual_analyze',analyzed,'voluntary_inspection',inspected,'later_day_activity',returned,'later_day_observable',later_day_observable,
 'inspection_later_day_observable',inspection_later_day_observable) END AS metrics FROM totals),
 bucket_sample AS(SELECT * FROM packed WHERE total=0
 ORDER BY coverage,source,medium,campaign,ref,referrer_domain,landing_route LIMIT 101)
 SELECT (SELECT metrics FROM packed WHERE total=1),
 (SELECT CASE WHEN count(*) BETWEEN 1 AND 100 AND bool_and(n>=p.min_cohort) THEN
 jsonb_agg(jsonb_build_object('coverage',coverage,'source',source,'medium',medium,'campaign',campaign,'ref',ref,
 'referrer_domain',referrer_domain,'landing_route',landing_route,'metrics',metrics)
 ORDER BY coverage,source,medium,campaign,ref,referrer_domain,landing_route)
 ELSE NULL END FROM bucket_sample) INTO result,attribution;
 RETURN jsonb_build_object('revision','funnel-v2','policy',p.revision,'unit',p_unit,'basis',p_basis,'calendar','UTC-v1',
 'since',p_since,'until',p_until,'generated_at',clock_timestamp(),'coverage_start','migration-0020',
 'freshness','capture/Analyze commit hooks; optional import observations require bounded reconciliation before reports','metrics',result,
 'import_reconciliation_coverage','enabled policy only; retained authoritative imports within fact retention may predate collection enablement; no signup or foreground-action reconstruction',
 'visitor_denominator','touch snapshots only; no all-traffic or visitor-conversion denominator',
 'attribution',attribution,'attribution_suppressed',attribution IS NULL,'attribution_bucket_limit',100,
 'traffic_qualification','opt-in assertion; human/bot/test status unknown',
 'human_return_revision','human-return-v1','human_return_coverage','explicit foreground Flare/evidence inspection only; collection loss unknown',
 'maturity','later_day_observable is a calendar opportunity, no retention rate selected');
END $$;
