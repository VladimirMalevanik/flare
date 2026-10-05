-- Paddle Sandbox only. Runtime never writes billing tables directly.
CREATE TABLE public.billing_checkout_intents (
 token_hash text PRIMARY KEY CHECK(token_hash ~ '^[0-9a-f]{64}$'),
 workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
 user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
 price_id text NOT NULL CHECK(price_id ~ '^pri_[a-z0-9]{26}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL,
 consumed_at timestamptz,
 subscription_id text UNIQUE,
 CHECK(expires_at > created_at),
 CHECK((consumed_at IS NULL) = (subscription_id IS NULL))
);
CREATE INDEX billing_intent_expiry ON public.billing_checkout_intents(expires_at);

CREATE TABLE public.billing_subscriptions (
 subscription_id text PRIMARY KEY CHECK(length(subscription_id) BETWEEN 5 AND 128),
 workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
 user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
 customer_id text NOT NULL CHECK(length(customer_id) BETWEEN 5 AND 128),
 environment text NOT NULL DEFAULT 'sandbox' CHECK(environment='sandbox'),
 bound_price_id text NOT NULL CHECK(bound_price_id ~ '^pri_[a-z0-9]{26}$'),
 price_id text,
 product_id text,
 quantity integer NOT NULL CHECK(quantity BETWEEN 0 AND 1000),
 status text NOT NULL CHECK(status IN ('active','trialing','paused','canceled','past_due','unknown')),
 trial_starts_at timestamptz, trial_ends_at timestamptz,
 current_period_starts_at timestamptz, current_period_ends_at timestamptz,
 next_billed_at timestamptz, scheduled_action text, scheduled_effective_at timestamptz,
 last_occurred_at timestamptz NOT NULL,
 state_fingerprint text NOT NULL CHECK(state_fingerprint ~ '^[0-9a-f]{64}$'),
 watermark_conflict boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX billing_subscription_workspace ON public.billing_subscriptions(workspace_id);

-- No raw webhook body, email, payment data or raw intent token is retained.
-- Pending snapshots prevent a late created event from restoring stale Pro access.
CREATE TABLE public.billing_webhook_events (
 event_id text PRIMARY KEY CHECK(length(event_id) BETWEEN 5 AND 128),
 payload_hash text NOT NULL CHECK(payload_hash ~ '^[0-9a-f]{64}$'),
 event_type text NOT NULL,
 subscription_id text NOT NULL,
 customer_id text NOT NULL,
 occurred_at timestamptz NOT NULL,
 received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 outcome text NOT NULL CHECK(outcome IN ('applied','stale','unlinked','conflict')),
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object')
);
CREATE INDEX billing_event_pending ON public.billing_webhook_events(subscription_id,occurred_at)
 WHERE outcome='unlinked';

CREATE FUNCTION public.create_billing_checkout_intent(p_hash text,p_price text,p_ttl integer)
 RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
 u text:=nullif(current_setting('app.user_id',true),''); expiry timestamptz;
BEGIN
 IF w IS NULL OR u IS NULL THEN
  RAISE EXCEPTION 'Billing owner required' USING ERRCODE='42501';
 END IF;
 IF p_hash IS NULL OR p_hash !~ '^[0-9a-f]{64}$' OR p_price IS NULL
  OR p_price !~ '^pri_[a-z0-9]{26}$' OR p_ttl IS NULL OR p_ttl NOT BETWEEN 60 AND 7200 THEN
  RAISE EXCEPTION 'Invalid checkout intent' USING ERRCODE='22023';
 END IF;
 PERFORM m.user_id FROM public.workspace_members m JOIN public.auth_users a ON a.id=m.user_id
  WHERE m.workspace_id=w AND m.user_id=u AND m.role='owner' AND NOT a.disabled
  FOR SHARE OF m,a;
 IF NOT FOUND THEN RAISE EXCEPTION 'Billing owner required' USING ERRCODE='42501'; END IF;
 expiry:=clock_timestamp()+make_interval(secs=>p_ttl);
 INSERT INTO public.billing_checkout_intents(token_hash,workspace_id,user_id,price_id,expires_at)
 VALUES(p_hash,w,u,p_price,expiry);
 RETURN expiry;
END $$;

CREATE FUNCTION public._apply_paddle_billing_event(p jsonb) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE e public.billing_webhook_events; b public.billing_subscriptions;
 i public.billing_checkout_intents; chosen jsonb; candidate jsonb; relevant jsonb;
 occurred timestamptz; stamp timestamptz; state_hash text; result_outcome text:='applied';
 created_binding boolean:=false; ambiguous boolean:=false;
BEGIN
 IF jsonb_typeof(p) IS DISTINCT FROM 'object'
  OR length(coalesce(p->>'event_id','')) NOT BETWEEN 5 AND 128
  OR length(coalesce(p->>'subscription_id','')) NOT BETWEEN 5 AND 128
  OR length(coalesce(p->>'customer_id','')) NOT BETWEEN 5 AND 128
  OR coalesce(p->>'payload_hash','') !~ '^[0-9a-f]{64}$'
  OR coalesce(p->>'event_type','') !~ '^subscription[.][a-z_]{1,40}$'
  OR coalesce(p->>'status','') NOT IN ('active','trialing','paused','canceled','past_due','unknown')
  OR jsonb_typeof(p->'quantity') IS DISTINCT FROM 'number'
  OR (p->>'quantity')::integer NOT BETWEEN 0 AND 1000
  OR (p->>'price_id' IS NOT NULL AND length(p->>'price_id')>128)
  OR (p->>'product_id' IS NOT NULL AND length(p->>'product_id')>128)
  OR (p->>'scheduled_action' IS NOT NULL AND length(p->>'scheduled_action')>40) THEN
  RAISE EXCEPTION 'Invalid billing snapshot' USING ERRCODE='22023';
 END IF;
 occurred:=(p->>'occurred_at')::timestamptz;
 IF occurred IS NULL OR NOT isfinite(occurred) OR occurred>clock_timestamp()+interval '5 minutes' THEN
  RAISE EXCEPTION 'Invalid event time' USING ERRCODE='22023';
 END IF;
 -- Only the normalized known fields are retained, including no browser userId.
 p:=jsonb_build_object('event_id',p->>'event_id','event_type',p->>'event_type',
  'occurred_at',occurred,'payload_hash',p->>'payload_hash',
  'subscription_id',p->>'subscription_id','customer_id',p->>'customer_id',
  'status',p->>'status','price_id',p->>'price_id','product_id',p->>'product_id',
  'quantity',(p->>'quantity')::integer,
  'trial_starts_at',(p->>'trial_starts_at')::timestamptz,
  'trial_ends_at',(p->>'trial_ends_at')::timestamptz,
  'current_period_starts_at',(p->>'current_period_starts_at')::timestamptz,
  'current_period_ends_at',(p->>'current_period_ends_at')::timestamptz,
  'next_billed_at',(p->>'next_billed_at')::timestamptz,
  'scheduled_action',p->>'scheduled_action',
  'scheduled_effective_at',(p->>'scheduled_effective_at')::timestamptz,
  'intent_hash',p->>'intent_hash');
 INSERT INTO public.billing_webhook_events(event_id,payload_hash,event_type,subscription_id,
  customer_id,occurred_at,outcome,snapshot)
 VALUES(p->>'event_id',p->>'payload_hash',p->>'event_type',p->>'subscription_id',
  p->>'customer_id',occurred,'unlinked',p) ON CONFLICT(event_id) DO NOTHING;
 IF NOT FOUND THEN
  SELECT * INTO e FROM public.billing_webhook_events WHERE event_id=p->>'event_id';
  IF e.payload_hash=p->>'payload_hash' THEN RETURN 'duplicate'; END IF;
  RETURN 'conflict';
 END IF;
 -- Serialize both existing-row updates and the first binding for this subscription.
 PERFORM pg_advisory_xact_lock(hashtextextended('flare:paddle:'||(p->>'subscription_id'),0));
 SELECT * INTO b FROM public.billing_subscriptions WHERE subscription_id=p->>'subscription_id' FOR UPDATE;
 IF NOT FOUND THEN
  IF p->>'event_type'<>'subscription.created' THEN RETURN 'unlinked'; END IF;
  SELECT * INTO i FROM public.billing_checkout_intents
   WHERE token_hash=p->>'intent_hash' FOR UPDATE;
  IF NOT FOUND OR i.consumed_at IS NOT NULL OR i.price_id IS DISTINCT FROM p->>'price_id'
   OR (p->>'quantity')::integer<>1 OR occurred<i.created_at OR occurred>i.expires_at
   OR clock_timestamp()>i.expires_at+interval '15 minutes' THEN RETURN 'unlinked'; END IF;
  PERFORM set_config('app.workspace_id',i.workspace_id::text,true);
  PERFORM set_config('app.user_id',i.user_id,true);
  PERFORM m.user_id FROM public.workspace_members m JOIN public.auth_users a ON a.id=m.user_id
   WHERE m.workspace_id=i.workspace_id AND m.user_id=i.user_id AND m.role='owner' AND NOT a.disabled
   FOR SHARE OF m,a;
  IF NOT FOUND THEN RETURN 'unlinked'; END IF;
  UPDATE public.billing_checkout_intents SET consumed_at=clock_timestamp(),subscription_id=p->>'subscription_id'
   WHERE token_hash=i.token_hash;
  created_binding:=true;
 ELSE
  IF b.customer_id IS DISTINCT FROM p->>'customer_id' THEN
   IF occurred<b.last_occurred_at THEN result_outcome:='stale';
   ELSE
    -- Paddle can transfer a customer. Never silently move a workspace's binding
    -- or leave its prior Pro grant eligible after a newer transfer/cancellation.
    UPDATE public.billing_subscriptions SET status='unknown',watermark_conflict=true,
     last_occurred_at=occurred,updated_at=clock_timestamp() WHERE subscription_id=b.subscription_id;
    result_outcome:='conflict';
   END IF;
   UPDATE public.billing_webhook_events SET outcome=result_outcome WHERE event_id=p->>'event_id';
   RETURN result_outcome;
  END IF;
 END IF;
 chosen:=p;
 IF created_binding THEN
  -- All stored snapshots reached this capability after backend signature checks.
  -- A pending customer transfer must poison eligibility rather than being lost.
  -- Only the initial created event fixes the immutable customer/workspace binding.
  SELECT max(occurred_at) INTO stamp FROM public.billing_webhook_events
   WHERE subscription_id=p->>'subscription_id' AND outcome='unlinked';
  FOR candidate IN SELECT snapshot FROM public.billing_webhook_events
   WHERE subscription_id=p->>'subscription_id' AND outcome='unlinked' AND occurred_at=stamp LOOP
   relevant:=candidate-ARRAY['event_id','event_type','occurred_at','payload_hash','intent_hash'];
   IF state_hash IS NOT NULL AND state_hash<>encode(sha256(convert_to(relevant::text,'UTF8')),'hex') THEN
    ambiguous:=true;
   END IF;
   state_hash:=encode(sha256(convert_to(relevant::text,'UTF8')),'hex');
   IF candidate->>'customer_id' IS DISTINCT FROM p->>'customer_id' THEN ambiguous:=true; END IF;
   chosen:=candidate;
  END LOOP;
 END IF;
 stamp:=(chosen->>'occurred_at')::timestamptz;
 relevant:=chosen-ARRAY['event_id','event_type','occurred_at','payload_hash','intent_hash'];
 state_hash:=encode(sha256(convert_to(relevant::text,'UTF8')),'hex');
 IF NOT created_binding THEN
  IF stamp<b.last_occurred_at THEN result_outcome:='stale';
  ELSIF stamp=b.last_occurred_at THEN
   IF state_hash=b.state_fingerprint AND NOT b.watermark_conflict THEN result_outcome:='stale';
   ELSE ambiguous:=true; END IF;
  END IF;
 END IF;
 IF result_outcome='stale' THEN
  UPDATE public.billing_webhook_events SET outcome='stale' WHERE event_id=p->>'event_id';
  RETURN 'stale';
 END IF;
 IF ambiguous THEN result_outcome:='conflict'; END IF;
 -- Unknown prices/quantities remain visible but never inherit a former Pro grant.
 INSERT INTO public.billing_subscriptions(subscription_id,workspace_id,user_id,customer_id,bound_price_id,
  price_id,product_id,quantity,status,trial_starts_at,trial_ends_at,current_period_starts_at,
  current_period_ends_at,next_billed_at,scheduled_action,scheduled_effective_at,last_occurred_at,
  state_fingerprint,watermark_conflict)
 VALUES(p->>'subscription_id',CASE WHEN created_binding THEN i.workspace_id ELSE b.workspace_id END,
  CASE WHEN created_binding THEN i.user_id ELSE b.user_id END,p->>'customer_id',
  CASE WHEN created_binding THEN i.price_id ELSE b.bound_price_id END,
  chosen->>'price_id',chosen->>'product_id',(chosen->>'quantity')::integer,
  CASE WHEN ambiguous THEN 'unknown' ELSE chosen->>'status' END,
  (chosen->>'trial_starts_at')::timestamptz,(chosen->>'trial_ends_at')::timestamptz,
  (chosen->>'current_period_starts_at')::timestamptz,(chosen->>'current_period_ends_at')::timestamptz,
  (chosen->>'next_billed_at')::timestamptz,chosen->>'scheduled_action',
  (chosen->>'scheduled_effective_at')::timestamptz,stamp,state_hash,ambiguous)
 ON CONFLICT(subscription_id) DO UPDATE SET price_id=excluded.price_id,product_id=excluded.product_id,
  quantity=excluded.quantity,status=excluded.status,trial_starts_at=excluded.trial_starts_at,
  trial_ends_at=excluded.trial_ends_at,current_period_starts_at=excluded.current_period_starts_at,
  current_period_ends_at=excluded.current_period_ends_at,next_billed_at=excluded.next_billed_at,
  scheduled_action=excluded.scheduled_action,scheduled_effective_at=excluded.scheduled_effective_at,
  last_occurred_at=excluded.last_occurred_at,state_fingerprint=excluded.state_fingerprint,
  watermark_conflict=excluded.watermark_conflict,updated_at=clock_timestamp();
 UPDATE public.billing_webhook_events SET outcome=result_outcome
  WHERE event_id=p->>'event_id';
 RETURN result_outcome;
END $$;

CREATE FUNCTION public.apply_paddle_billing_event(p jsonb) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE previous_workspace text:=coalesce(current_setting('app.workspace_id',true),'');
 previous_user text:=coalesce(current_setting('app.user_id',true),''); result text;
BEGIN
 -- Function-level SET on custom placeholders requires extra parameter privileges
 -- on managed PostgreSQL. Runtime-local set_config needs no owner escalation.
 PERFORM set_config('app.workspace_id','',true);
 PERFORM set_config('app.user_id','',true);
 result:=public._apply_paddle_billing_event(p);
 PERFORM set_config('app.workspace_id',previous_workspace,true);
 PERFORM set_config('app.user_id',previous_user,true);
 RETURN result;
 -- If any statement raises, PostgreSQL rolls back the whole call (including all
 -- its LOCAL settings). Repository transactions never return an aborted pool conn.
END $$;
