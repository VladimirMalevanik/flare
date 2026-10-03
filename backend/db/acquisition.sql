-- GROWTH contract v1. Configuration has NO approved production defaults.
CREATE TABLE public.growth_policy (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), enabled boolean NOT NULL DEFAULT false,
 revision text, notice_id text, eligibility text, cleanup_owner text,
 lookback_seconds int, cookie_seconds int, raw_seconds int, linked_seconds int, fact_seconds int,
 global_hour int, network_hour int, reference_limit int, visitor_limit int, budget_limit int, deadline_ms int,
 min_cohort int, report_window_days int, report_calendar text,
 tokens jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(tokens)='object' AND octet_length(tokens::text)<=4096),
 CHECK(NOT enabled OR COALESCE((length(revision) BETWEEN 1 AND 80 AND notice_id IS NOT NULL AND cleanup_owner IS NOT NULL
 AND eligibility='explicit-opt-in' AND report_calendar='UTC-v1'
 AND lookback_seconds>0 AND cookie_seconds>0 AND raw_seconds>0 AND linked_seconds>0 AND fact_seconds>0
 AND global_hour BETWEEN 1 AND 100000 AND network_hour BETWEEN 1 AND global_hour
 AND reference_limit BETWEEN 1 AND 100 AND visitor_limit BETWEEN 1 AND 1000000
 AND budget_limit BETWEEN 2 AND 1000000
 AND deadline_ms BETWEEN 10 AND 2000 AND min_cohort BETWEEN 2 AND 1000 AND report_window_days BETWEEN 1 AND 90),false))
);
INSERT INTO public.growth_policy(singleton) VALUES(true);
CREATE TABLE public.acquisition_visitors (
 reference_hash text PRIMARY KEY CHECK(reference_hash ~ '^[a-f0-9]{64}$'),
 first_touch jsonb NOT NULL, last_touch jsonb, revision text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), expires_at timestamptz NOT NULL,
 touches int NOT NULL DEFAULT 1 CHECK(touches BETWEEN 1 AND 100)
);
CREATE INDEX acquisition_expiry ON public.acquisition_visitors(expires_at);
CREATE TABLE public.acquisition_budgets (
 bucket text PRIMARY KEY CHECK(length(bucket)<=70), hour timestamptz NOT NULL, attempts int NOT NULL
);
CREATE TABLE public.signup_attribution (
 user_id text PRIMARY KEY REFERENCES public.auth_users(id) ON DELETE CASCADE,
 workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL, eligibility text NOT NULL DEFAULT 'unknown'
 CHECK(eligibility IN ('eligible','unknown','withdrawn')), revision text,
 first_touch jsonb, last_touch jsonb, finalized boolean NOT NULL DEFAULT false
);
CREATE INDEX signup_cohort ON public.signup_attribution(created_at,workspace_id);
CREATE TABLE public.growth_workspace_optouts (
 workspace_id uuid PRIMARY KEY REFERENCES public.workspaces(id) ON DELETE CASCADE
);
CREATE FUNCTION public.acquisition_policy() RETURNS jsonb LANGUAGE sql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT CASE WHEN enabled THEN jsonb_build_object('enabled',true,'revision',revision,'noticeId',notice_id,
 'eligibility',eligibility,'cookieSeconds',cookie_seconds,'deadlineMs',deadline_ms) ELSE jsonb_build_object('enabled',false) END FROM public.growth_policy;
$$;
CREATE FUNCTION public.acquisition_touch(p_ref text,p_network text,p_touch jsonb,p_revision text,p_new boolean) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.growth_policy; k text; v text; n int; t jsonb; direct boolean;
BEGIN
 SELECT * INTO p FROM public.growth_policy;
 IF NOT p.enabled OR p_revision IS DISTINCT FROM p.revision OR p_ref IS NULL OR p_ref !~ '^[a-f0-9]{64}$'
 OR p_network IS NULL OR p_network !~ '^[a-f0-9]{64}$' OR jsonb_typeof(p_touch) IS DISTINCT FROM 'object'
 OR octet_length(p_touch::text)>1024 THEN RETURN false; END IF;
 IF NOT pg_try_advisory_xact_lock(2020,1) THEN RETURN false; END IF;
 -- Count rejected policy input too. A new cookie cannot reset this budget.
 FOREACH k IN ARRAY ARRAY['global',p_network] LOOP
  IF NOT EXISTS(SELECT 1 FROM public.acquisition_budgets WHERE bucket=k)
  AND (SELECT count(*) FROM public.acquisition_budgets)>=p.budget_limit THEN RETURN false; END IF;
  INSERT INTO public.acquisition_budgets(bucket,hour,attempts) VALUES(k,date_trunc('hour',clock_timestamp()),1)
  ON CONFLICT(bucket) DO UPDATE SET hour=excluded.hour,attempts=CASE WHEN acquisition_budgets.hour=excluded.hour
  THEN least(acquisition_budgets.attempts+1,p.global_hour+1) ELSE 1 END RETURNING attempts INTO n;
  IF n>(CASE WHEN k='global' THEN p.global_hour ELSE p.network_hour END) THEN RETURN false; END IF;
 END LOOP;
 FOR k,v IN SELECT key,value FROM jsonb_each_text(p_touch) LOOP
  IF k NOT IN ('utm_source','utm_medium','utm_campaign','utm_content','ref','referrer_domain','landing_route')
  OR length(v)>80 OR v !~ '^[a-z0-9/._-]+$' OR jsonb_typeof(p_touch->k)<>'string' THEN RETURN false; END IF;
  IF k='landing_route' THEN
   IF v NOT IN ('/','/login','/register') THEN RETURN false; END IF;
  ELSIF NOT COALESCE((p.tokens->k) ? v,false) THEN RETURN false; END IF;
 END LOOP;
 IF NOT p_touch ? 'landing_route' THEN RETURN false; END IF;
 direct := NOT (p_touch ?| ARRAY['utm_source','utm_medium','utm_campaign','ref','referrer_domain']);
 t := p_touch || jsonb_build_object('observed_at',clock_timestamp(),'revision',p.revision);
 IF EXISTS(SELECT 1 FROM public.acquisition_visitors WHERE reference_hash=p_ref) THEN
  UPDATE public.acquisition_visitors SET touches=touches+1,last_touch=CASE WHEN direct THEN last_touch ELSE t END
  WHERE reference_hash=p_ref AND expires_at>clock_timestamp() AND touches<p.reference_limit AND revision=p.revision;
  RETURN FOUND;
 END IF;
 IF NOT p_new THEN RETURN false; END IF;
 IF (SELECT count(*) FROM public.acquisition_visitors)>=p.visitor_limit THEN RETURN false; END IF;
 INSERT INTO public.acquisition_visitors(reference_hash,first_touch,last_touch,revision,expires_at)
 VALUES(p_ref,t,CASE WHEN direct THEN NULL ELSE t END,p.revision,
 clock_timestamp()+make_interval(secs=>least(p.raw_seconds,p.cookie_seconds,p.lookback_seconds)));
 RETURN true;
END $$;
ALTER TABLE public.auth_users ADD COLUMN verification_provenance text NOT NULL DEFAULT 'legacy_unknown'
 CHECK(verification_provenance IN ('pending','bypassed','actual','legacy_unknown'));
CREATE INDEX growth_auth_cohort ON public.auth_users(created_at,id);
-- Auth owns account/verification truth. No auxiliary trigger runs on signup or verification.
CREATE FUNCTION public.acquisition_freeze(p_ref text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.signup_attribution; v public.acquisition_visitors; p public.growth_policy;
BEGIN
 SELECT * INTO p FROM public.growth_policy;
 IF NOT COALESCE(p.enabled,false) THEN RETURN; END IF;
 -- Only the original account transaction can create the optional snapshot. A failed
 -- savepoint leaves a visible gap, never something rebuilt from later login/touch.
 INSERT INTO public.signup_attribution(user_id,workspace_id,created_at,finalized)
 SELECT id,initial_workspace_id,created_at,true FROM public.auth_users
 WHERE id=nullif(current_setting('app.user_id',true),'') AND created_at=transaction_timestamp()
 AND verification_provenance='pending'
 ON CONFLICT DO NOTHING RETURNING * INTO a;
 IF a.user_id IS NULL THEN RETURN; END IF;
 IF p_ref ~ '^[a-f0-9]{64}$' THEN
  DELETE FROM public.acquisition_visitors WHERE reference_hash=p_ref AND expires_at>clock_timestamp()
  AND revision=p.revision RETURNING * INTO v;
 END IF;
 UPDATE public.signup_attribution SET finalized=true,eligibility=CASE WHEN v.reference_hash IS NULL THEN 'unknown' ELSE 'eligible' END,
 revision=v.revision,first_touch=v.first_touch,last_touch=v.last_touch WHERE user_id=a.user_id;
END $$;

CREATE FUNCTION public.acquisition_forget(p_ref text) RETURNS void LANGUAGE sql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ DELETE FROM public.acquisition_visitors WHERE reference_hash=p_ref; $$;
