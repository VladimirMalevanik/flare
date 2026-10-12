-- Team policy is deployment configuration, never writable by runtime roles.
CREATE TABLE public.team_policy (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 enabled boolean NOT NULL DEFAULT false,
 price_id text CHECK(price_id ~ '^pri_[a-z0-9]{26}$'),
 max_projects integer NOT NULL DEFAULT 1 CHECK(max_projects BETWEEN 1 AND 5),
 max_members integer NOT NULL DEFAULT 10 CHECK(max_members BETWEEN 2 AND 100),
 max_tasks integer NOT NULL DEFAULT 1000 CHECK(max_tasks BETWEEN 1 AND 10000),
 max_invites_daily integer NOT NULL DEFAULT 20 CHECK(max_invites_daily BETWEEN 1 AND 100),
 max_documents integer NOT NULL DEFAULT 5000 CHECK(max_documents BETWEEN 1 AND 10000),
 max_content_bytes bigint NOT NULL DEFAULT 104857600 CHECK(max_content_bytes BETWEEN 1048576 AND 1073741824),
 CHECK(NOT enabled OR price_id IS NOT NULL)
);
INSERT INTO public.team_policy(singleton) VALUES(true);
CREATE TABLE public.team_projects (
 workspace_id uuid PRIMARY KEY REFERENCES public.workspaces(id),
 license_workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
 created_by text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(workspace_id<>license_workspace_id)
);
CREATE INDEX team_project_license ON public.team_projects(license_workspace_id);
CREATE TABLE public.team_invitations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.team_projects(workspace_id),
 email text NOT NULL CHECK(email=lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
 role text NOT NULL CHECK(role IN ('editor','viewer')),
 token_hash text NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'),
 invited_by text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '7 days',
 consumed_at timestamptz, canceled_at timestamptz,
 accepted_by text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 CHECK(expires_at>created_at)
);
CREATE UNIQUE INDEX team_invite_pending ON public.team_invitations(workspace_id,email)
 WHERE consumed_at IS NULL AND canceled_at IS NULL;
CREATE INDEX team_invite_daily ON public.team_invitations(workspace_id,created_at);
CREATE TABLE public.team_tasks (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.team_projects(workspace_id),
 title text NOT NULL CHECK(length(btrim(title)) BETWEEN 1 AND 180),
 description text NOT NULL DEFAULT '' CHECK(octet_length(description)<=10000),
 status text NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done')),
 created_by text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 creator_name text NOT NULL CHECK(length(creator_name) BETWEEN 1 AND 100),
 assignee_id text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 deleted_at timestamptz,
 UNIQUE(workspace_id,id)
);
CREATE INDEX team_task_list ON public.team_tasks(workspace_id,updated_at DESC,id) WHERE deleted_at IS NULL;
CREATE TABLE public.team_task_history (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL,
 task_id uuid NOT NULL,
 actor_id text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 actor_name text NOT NULL,
 action text NOT NULL CHECK(action IN ('created','updated','deleted','unassigned')),
 fields text[] NOT NULL DEFAULT '{}',
 version integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(workspace_id,task_id) REFERENCES public.team_tasks(workspace_id,id) ON DELETE CASCADE
);
CREATE INDEX team_task_history_list ON public.team_task_history(workspace_id,task_id,created_at DESC,id);
CREATE TABLE public.team_member_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 workspace_id uuid NOT NULL REFERENCES public.team_projects(workspace_id),
 actor_id text REFERENCES public.auth_users(id) ON DELETE SET NULL,
 target_id text,
 action text NOT NULL CHECK(action IN ('joined','removed','left','role','ownership')),
 role text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX team_member_event_list ON public.team_member_events(workspace_id,created_at DESC);

CREATE FUNCTION public._team_actor() RETURNS public.auth_users
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.auth_users;
BEGIN
 SELECT * INTO a FROM public.auth_users WHERE id=nullif(current_setting('app.user_id',true),'') AND NOT disabled;
 IF NOT FOUND OR a.email_verified_at IS NULL OR a.verification_provenance<>'actual' THEN
  RAISE EXCEPTION 'Verified account required' USING ERRCODE='42501';
 END IF;
 RETURN a;
END $$;

CREATE FUNCTION public._team_paid(w uuid) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_policy; b public.billing_subscriptions; t timestamptz:=clock_timestamp(); s timestamptz; e timestamptz;
BEGIN
 SELECT * INTO p FROM public.team_policy WHERE singleton FOR SHARE;
 IF NOT p.enabled OR p.price_id IS NULL THEN RETURN false; END IF;
 FOR b IN SELECT * FROM public.billing_subscriptions WHERE workspace_id=w FOR SHARE LOOP
  IF b.environment<>'sandbox' OR b.watermark_conflict OR b.price_id IS DISTINCT FROM p.price_id OR b.quantity<>1
    OR b.status NOT IN ('active','trialing') THEN CONTINUE; END IF;
  s:=CASE WHEN b.status='trialing' THEN b.trial_starts_at ELSE b.current_period_starts_at END;
  e:=CASE WHEN b.status='trialing' THEN b.trial_ends_at ELSE b.current_period_ends_at END;
  IF s IS NULL OR e IS NULL OR NOT (s<=t AND t<e) THEN CONTINUE; END IF;
  IF b.scheduled_action IN ('cancel','pause') AND (b.scheduled_effective_at IS NULL OR b.scheduled_effective_at<=t) THEN CONTINUE; END IF;
  RETURN true;
 END LOOP;
 RETURN false;
END $$;

CREATE FUNCTION public._team_guard(w uuid,needed text DEFAULT 'read') RETURNS public.team_projects
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.auth_users:=public._team_actor(); p public.team_projects; r text;
BEGIN
 SELECT * INTO p FROM public.team_projects WHERE workspace_id=w FOR UPDATE;
 SELECT role INTO r FROM public.workspace_members WHERE workspace_id=w AND user_id=a.id FOR SHARE;
 IF p.workspace_id IS NULL OR r IS NULL THEN RAISE EXCEPTION 'Project not found' USING ERRCODE='P0002'; END IF;
 IF needed='owner' AND r<>'owner' OR needed='write' AND r NOT IN ('owner','editor') THEN
  RAISE EXCEPTION 'Permission required' USING ERRCODE='42501';
 END IF;
 IF needed='write' AND NOT public._team_paid(p.license_workspace_id) THEN
  RAISE EXCEPTION 'Team subscription required' USING ERRCODE='P0001';
 END IF;
 PERFORM set_config('app.workspace_id',w::text,true);
 RETURN p;
END $$;

CREATE FUNCTION public.team_projects_list() RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE u text:=nullif(current_setting('app.user_id',true),''); result jsonb;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.auth_users WHERE id=u AND NOT disabled) THEN
  RAISE EXCEPTION 'Account required' USING ERRCODE='42501'; END IF;
 SELECT coalesce(jsonb_agg(x),'[]') INTO result FROM (
  SELECT w.id,w.name,m.role,CASE WHEN p.workspace_id IS NULL THEN 'personal' ELSE 'team' END AS kind,
   CASE WHEN p.workspace_id IS NULL THEN true ELSE public._team_paid(p.license_workspace_id) END AS writable,
   (p.license_workspace_id IS NOT NULL AND EXISTS(SELECT 1 FROM public.workspace_members lm
    WHERE lm.workspace_id=p.license_workspace_id AND lm.user_id=u AND lm.role='owner')) AS "canManageLicense"
  FROM public.workspace_members m JOIN public.workspaces w ON w.id=m.workspace_id
   LEFT JOIN public.team_projects p ON p.workspace_id=w.id
  WHERE m.user_id=u ORDER BY (p.workspace_id IS NOT NULL),w.created_at,w.id LIMIT 100
 ) x;
 RETURN result;
END $$;

CREATE FUNCTION public.team_capability() RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_policy; a public.auth_users; count_projects integer;
BEGIN
 SELECT * INTO p FROM public.team_policy WHERE singleton;
 SELECT * INTO a FROM public.auth_users WHERE id=nullif(current_setting('app.user_id',true),'') AND NOT disabled;
 IF a.id IS NULL THEN RAISE EXCEPTION 'Account required' USING ERRCODE='42501'; END IF;
 SELECT count(*) INTO count_projects FROM public.team_projects WHERE license_workspace_id=a.initial_workspace_id;
 RETURN jsonb_build_object('enabled',p.enabled,'canCreate',p.enabled AND a.verification_provenance='actual'
   AND a.email_verified_at IS NOT NULL AND public._team_paid(a.initial_workspace_id) AND count_projects<p.max_projects,
   'requiresVerification',a.verification_provenance IS DISTINCT FROM 'actual' OR a.email_verified_at IS NULL,
   'limits',jsonb_build_object('projects',p.max_projects,'members',p.max_members,'tasks',p.max_tasks,
    'documents',p.max_documents,'contentBytes',p.max_content_bytes,'invitationsDaily',p.max_invites_daily),
   'projectCount',count_projects,'priceId',p.price_id);
END $$;

CREATE FUNCTION public.team_project_create(new_id uuid,new_name text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.auth_users:=public._team_actor(); p public.team_policy; existing public.team_projects;
BEGIN
 IF new_id IS NULL OR length(btrim(new_name)) NOT BETWEEN 1 AND 100 THEN
  RAISE EXCEPTION 'Invalid project' USING ERRCODE='22023'; END IF;
 PERFORM id FROM public.workspaces WHERE id=a.initial_workspace_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=a.initial_workspace_id AND user_id=a.id AND role='owner')
   OR NOT public._team_paid(a.initial_workspace_id) THEN
  RAISE EXCEPTION 'Team subscription required' USING ERRCODE='P0001'; END IF;
 SELECT * INTO existing FROM public.team_projects WHERE workspace_id=new_id;
 IF FOUND THEN
  IF existing.created_by=a.id AND existing.license_workspace_id=a.initial_workspace_id THEN RETURN new_id; END IF;
  RAISE EXCEPTION 'Project not found' USING ERRCODE='P0002';
 END IF;
 SELECT * INTO p FROM public.team_policy WHERE singleton;
 IF (SELECT count(*) FROM public.team_projects WHERE license_workspace_id=a.initial_workspace_id)>=p.max_projects THEN
  RAISE EXCEPTION 'Project limit reached' USING ERRCODE='P0003'; END IF;
 INSERT INTO public.workspaces(id,name) VALUES(new_id,btrim(new_name));
 INSERT INTO public.workspace_members(workspace_id,user_id,role) VALUES(new_id,a.id,'owner');
 INSERT INTO public.team_projects(workspace_id,license_workspace_id,created_by) VALUES(new_id,a.initial_workspace_id,a.id);
 RETURN new_id;
END $$;

CREATE FUNCTION public.team_members_list(w uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w); result jsonb; owner boolean;
BEGIN
 SELECT role='owner' INTO owner FROM public.workspace_members WHERE workspace_id=w AND user_id=current_setting('app.user_id',true);
 SELECT coalesce(jsonb_agg(x),'[]') INTO result FROM (
  SELECT m.user_id AS id,a.name,m.role,CASE WHEN owner THEN a.email ELSE NULL END AS email
   FROM public.workspace_members m JOIN public.auth_users a ON a.id=m.user_id WHERE m.workspace_id=w
   ORDER BY (m.role='owner') DESC,a.name,m.user_id LIMIT 100
 ) x;
 RETURN result;
END $$;

CREATE FUNCTION public.team_invite(w uuid,mail text,new_role text,digest text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w,'owner'); policy public.team_policy; inv public.team_invitations;
BEGIN
 IF NOT public._team_paid(p.license_workspace_id) THEN RAISE EXCEPTION 'Team subscription required' USING ERRCODE='P0001'; END IF;
 IF mail IS NULL OR mail<>lower(btrim(mail)) OR length(mail) NOT BETWEEN 3 AND 254 OR mail !~ '^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$'
  OR new_role IS NULL OR new_role NOT IN ('editor','viewer') OR digest IS NULL OR digest !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Invalid invitation' USING ERRCODE='22023'; END IF;
 SELECT * INTO policy FROM public.team_policy WHERE singleton;
 IF EXISTS(SELECT 1 FROM public.workspace_members m JOIN public.auth_users a ON a.id=m.user_id WHERE m.workspace_id=w AND a.email=mail) THEN
  RAISE EXCEPTION 'Already a member' USING ERRCODE='P0003'; END IF;
 -- Pending invitations reserve seats. Resends replace the same reservation.
 UPDATE public.team_invitations SET canceled_at=clock_timestamp() WHERE workspace_id=w AND consumed_at IS NULL AND canceled_at IS NULL
  AND (email=mail OR expires_at<=clock_timestamp());
 DELETE FROM public.team_invitations WHERE workspace_id=w AND created_at<clock_timestamp()-interval '30 days';
 IF (SELECT count(*) FROM public.team_invitations WHERE workspace_id=w AND created_at>clock_timestamp()-interval '24 hours')>=policy.max_invites_daily THEN
  RAISE EXCEPTION 'Invitation limit reached' USING ERRCODE='P0003'; END IF;
 IF (SELECT count(*) FROM public.workspace_members WHERE workspace_id=w)+(SELECT count(*) FROM public.team_invitations
  WHERE workspace_id=w AND consumed_at IS NULL AND canceled_at IS NULL AND expires_at>clock_timestamp())>=policy.max_members THEN
  RAISE EXCEPTION 'Member limit reached' USING ERRCODE='P0003'; END IF;
 IF EXISTS(SELECT 1 FROM public.team_invitations WHERE workspace_id=w AND email=mail AND created_at>clock_timestamp()-interval '60 seconds') THEN
  RAISE EXCEPTION 'Wait before sending again' USING ERRCODE='P0003'; END IF;
 INSERT INTO public.team_invitations(workspace_id,email,role,token_hash,invited_by)
 VALUES(w,mail,new_role,digest,current_setting('app.user_id',true)) RETURNING * INTO inv;
 RETURN jsonb_build_object('id',inv.id,'expiresAt',inv.expires_at);
END $$;

CREATE FUNCTION public.team_invitations_list(w uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w,'owner'); result jsonb;
BEGIN
 SELECT coalesce(jsonb_agg(x),'[]') INTO result FROM (
  SELECT id,email,role,created_at AS "createdAt",expires_at AS "expiresAt",
   CASE WHEN consumed_at IS NOT NULL THEN 'accepted' WHEN canceled_at IS NOT NULL THEN 'canceled'
    WHEN expires_at<=clock_timestamp() THEN 'expired' ELSE 'pending' END AS status
  FROM public.team_invitations WHERE workspace_id=w ORDER BY created_at DESC,id LIMIT 100
 ) x; RETURN result;
END $$;

CREATE FUNCTION public.team_invitation_cancel(w uuid,inv_id uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w,'owner');
BEGIN
 UPDATE public.team_invitations SET canceled_at=coalesce(canceled_at,clock_timestamp()) WHERE workspace_id=w AND id=inv_id AND consumed_at IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'Invitation not found' USING ERRCODE='P0002'; END IF;
END $$;

CREATE FUNCTION public.team_invitation_accept(digest text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.auth_users:=public._team_actor(); inv public.team_invitations; p public.team_projects; policy public.team_policy;
BEGIN
 SELECT * INTO inv FROM public.team_invitations WHERE token_hash=digest;
 IF NOT FOUND OR inv.email<>a.email THEN RAISE EXCEPTION 'Invitation unavailable for this account' USING ERRCODE='P0002'; END IF;
 -- All membership changes share the same project lock, including accept vs cancel.
 SELECT * INTO p FROM public.team_projects WHERE workspace_id=inv.workspace_id FOR UPDATE;
 SELECT * INTO inv FROM public.team_invitations WHERE token_hash=digest FOR UPDATE;
 IF inv.consumed_at IS NOT NULL AND inv.accepted_by=a.id AND EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=inv.workspace_id AND user_id=a.id) THEN
  RETURN jsonb_build_object('workspaceId',inv.workspace_id); END IF;
 IF inv.canceled_at IS NOT NULL OR inv.consumed_at IS NOT NULL OR inv.expires_at<=clock_timestamp() THEN
  RAISE EXCEPTION 'Invitation expired or canceled' USING ERRCODE='P0002'; END IF;
 IF NOT public._team_paid(p.license_workspace_id) THEN RAISE EXCEPTION 'Team subscription required' USING ERRCODE='P0001'; END IF;
 IF (SELECT count(*) FROM public.workspace_members WHERE user_id=a.id)>=100 THEN RAISE EXCEPTION 'Project membership limit reached' USING ERRCODE='P0003'; END IF;
 SELECT * INTO policy FROM public.team_policy WHERE singleton;
 IF (SELECT count(*) FROM public.workspace_members WHERE workspace_id=p.workspace_id)>=policy.max_members THEN
  RAISE EXCEPTION 'Member limit reached' USING ERRCODE='P0003'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=p.workspace_id AND user_id=inv.invited_by AND role='owner') THEN
  RAISE EXCEPTION 'Invitation is no longer authorized' USING ERRCODE='P0002'; END IF;
 INSERT INTO public.workspace_members(workspace_id,user_id,role) VALUES(inv.workspace_id,a.id,inv.role)
  ON CONFLICT(workspace_id,user_id) DO NOTHING;
 UPDATE public.team_invitations SET consumed_at=clock_timestamp(),accepted_by=a.id WHERE id=inv.id;
 INSERT INTO public.team_member_events(workspace_id,actor_id,target_id,action,role) VALUES(inv.workspace_id,a.id,a.id,'joined',inv.role);
 RETURN jsonb_build_object('workspaceId',inv.workspace_id);
END $$;

CREATE FUNCTION public.team_membership_change(w uuid,target text,action text,new_role text DEFAULT NULL) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w); a public.auth_users:=public._team_actor(); caller_role text; target_role text; task public.team_tasks;
BEGIN
 SELECT role INTO caller_role FROM public.workspace_members WHERE workspace_id=w AND user_id=a.id;
 SELECT role INTO target_role FROM public.workspace_members WHERE workspace_id=w AND user_id=target FOR UPDATE;
 IF target_role IS NULL THEN RAISE EXCEPTION 'Member not found' USING ERRCODE='P0002'; END IF;
 IF action NOT IN ('remove','leave','role','transfer') OR (action='leave' AND target<>a.id)
  OR (action<>'leave' AND caller_role<>'owner') THEN RAISE EXCEPTION 'Owner required' USING ERRCODE='42501'; END IF;
 IF action='transfer' THEN
  IF target=a.id OR NOT EXISTS(SELECT 1 FROM public.auth_users WHERE id=target AND NOT disabled AND email_verified_at IS NOT NULL AND verification_provenance='actual') THEN
   RAISE EXCEPTION 'Verified successor required' USING ERRCODE='22023'; END IF;
  UPDATE public.workspace_members SET role='owner' WHERE workspace_id=w AND user_id=target;
  UPDATE public.workspace_members SET role='editor' WHERE workspace_id=w AND user_id=a.id;
  UPDATE public.team_invitations SET canceled_at=clock_timestamp() WHERE workspace_id=w AND invited_by=a.id AND consumed_at IS NULL AND canceled_at IS NULL;
  UPDATE public.analysis_schedules SET updated_by_user_id=target WHERE workspace_id=w;
  INSERT INTO public.team_member_events(workspace_id,actor_id,target_id,action,role) VALUES(w,a.id,target,'ownership','owner');
 ELSE
  IF target_role='owner' THEN RAISE EXCEPTION 'Transfer ownership first' USING ERRCODE='P0003'; END IF;
  IF action='role' THEN
   IF new_role IS NULL OR new_role NOT IN ('editor','viewer') THEN RAISE EXCEPTION 'Invalid role' USING ERRCODE='22023'; END IF;
   UPDATE public.workspace_members SET role=new_role WHERE workspace_id=w AND user_id=target;
   INSERT INTO public.team_member_events(workspace_id,actor_id,target_id,action,role) VALUES(w,a.id,target,'role',new_role);
  ELSE
   DELETE FROM public.workspace_members WHERE workspace_id=w AND user_id=target;
   UPDATE public.team_invitations SET canceled_at=clock_timestamp() WHERE workspace_id=w AND consumed_at IS NULL AND canceled_at IS NULL AND invited_by=target;
   FOR task IN UPDATE public.team_tasks SET assignee_id=NULL,version=version+1,updated_at=clock_timestamp()
     WHERE workspace_id=w AND assignee_id=target AND deleted_at IS NULL RETURNING * LOOP
    INSERT INTO public.team_task_history(workspace_id,task_id,actor_id,actor_name,action,fields,version)
     VALUES(w,task.id,a.id,a.name,'unassigned',ARRAY['assigneeId'],task.version);
    DELETE FROM public.team_task_history WHERE workspace_id=w AND task_id=task.id AND id NOT IN
     (SELECT id FROM public.team_task_history WHERE workspace_id=w AND task_id=task.id ORDER BY created_at DESC,id DESC LIMIT 50);
   END LOOP;
   INSERT INTO public.team_member_events(workspace_id,actor_id,target_id,action) VALUES(w,a.id,target,CASE WHEN action='leave' THEN 'left' ELSE 'removed' END);
  END IF;
 END IF;
 DELETE FROM public.team_member_events WHERE workspace_id=w AND id NOT IN(SELECT id FROM public.team_member_events WHERE workspace_id=w ORDER BY created_at DESC,id LIMIT 1000);
END $$;

CREATE FUNCTION public.team_tasks_list(w uuid,before_at timestamptz DEFAULT NULL,before_id uuid DEFAULT NULL) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w); result jsonb;
BEGIN
 SELECT coalesce(jsonb_agg(x),'[]') INTO result FROM (
  SELECT t.id,t.title,t.description,t.status,t.created_by AS "createdBy",t.creator_name AS "creatorName",
   t.assignee_id AS "assigneeId",a.name AS "assigneeName",t.version,t.created_at AS "createdAt",t.updated_at AS "updatedAt"
  FROM public.team_tasks t LEFT JOIN public.auth_users a ON a.id=t.assignee_id WHERE t.workspace_id=w AND t.deleted_at IS NULL
   AND (before_at IS NULL OR (t.updated_at,t.id)<(before_at,before_id)) ORDER BY t.updated_at DESC,t.id DESC LIMIT 101
 ) x; RETURN result;
END $$;

CREATE FUNCTION public.team_task_write(w uuid,task_id uuid,expected integer,payload jsonb,remove boolean DEFAULT false) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
#variable_conflict use_variable
DECLARE p public.team_projects:=public._team_guard(w,'write'); a public.auth_users:=public._team_actor(); task public.team_tasks;
 policy public.team_policy; title text; body text; status text; assigned text; fields text[]; fresh boolean;
BEGIN
 IF task_id IS NULL OR expected IS NULL OR expected<0 OR remove IS NULL OR payload IS NULL OR jsonb_typeof(payload)<>'object' OR EXISTS(SELECT 1 FROM jsonb_object_keys(payload) k WHERE k NOT IN ('title','description','status','assigneeId')) THEN
  RAISE EXCEPTION 'Invalid task' USING ERRCODE='22023'; END IF;
 SELECT * INTO task FROM public.team_tasks WHERE workspace_id=w AND id=task_id FOR UPDATE;
 fresh:=NOT FOUND;
 IF fresh THEN
  IF expected<>0 OR remove THEN RAISE EXCEPTION 'Task not found' USING ERRCODE='P0002'; END IF;
  SELECT * INTO policy FROM public.team_policy WHERE singleton;
  -- Total rows are bounded as well as visible tasks; deletion cannot amplify storage.
  IF (SELECT count(*) FROM public.team_tasks WHERE workspace_id=w)>=policy.max_tasks THEN RAISE EXCEPTION 'Task limit reached' USING ERRCODE='P0003'; END IF;
 ELSIF task.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'Task not found' USING ERRCODE='P0002';
 ELSIF expected=0 AND task.created_by=a.id AND NOT remove AND task.version=1 AND task.title=payload->>'title'
   AND task.description=coalesce(payload->>'description','') AND task.status=coalesce(payload->>'status','todo')
   AND task.assignee_id IS NOT DISTINCT FROM payload->>'assigneeId' THEN
  RETURN jsonb_build_object('id',task.id,'version',task.version);
 ELSIF expected IS DISTINCT FROM task.version THEN RAISE EXCEPTION 'Task changed; reload before saving' USING ERRCODE='40001'; END IF;
 title:=CASE WHEN payload?'title' THEN btrim(payload->>'title') ELSE task.title END;
 body:=CASE WHEN payload?'description' THEN payload->>'description' ELSE coalesce(task.description,'') END;
 status:=CASE WHEN payload?'status' THEN payload->>'status' ELSE coalesce(task.status,'todo') END;
 assigned:=CASE WHEN payload?'assigneeId' THEN payload->>'assigneeId' ELSE task.assignee_id END;
 IF NOT remove AND (title IS NULL OR length(title) NOT BETWEEN 1 AND 180 OR body IS NULL OR octet_length(body)>10000 OR status IS NULL OR status NOT IN ('todo','doing','done')) THEN
  RAISE EXCEPTION 'Invalid task' USING ERRCODE='22023'; END IF;
 IF assigned IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.workspace_members m JOIN public.auth_users u ON u.id=m.user_id WHERE m.workspace_id=w AND m.user_id=assigned AND NOT u.disabled) THEN
  RAISE EXCEPTION 'Assignee must be a project member' USING ERRCODE='22023'; END IF;
 fields:=ARRAY(SELECT jsonb_object_keys(payload));
 IF fresh THEN
  INSERT INTO public.team_tasks(id,workspace_id,title,description,status,created_by,creator_name,assignee_id)
   VALUES(task_id,w,title,body,status,a.id,a.name,assigned) RETURNING * INTO task;
 ELSE
  UPDATE public.team_tasks SET title=CASE WHEN remove THEN team_tasks.title ELSE title END,
   description=CASE WHEN remove THEN team_tasks.description ELSE body END,status=CASE WHEN remove THEN team_tasks.status ELSE status END,
   assignee_id=assigned,deleted_at=CASE WHEN remove THEN clock_timestamp() ELSE NULL END,version=version+1,updated_at=clock_timestamp()
   WHERE workspace_id=w AND id=task_id RETURNING * INTO task;
 END IF;
 INSERT INTO public.team_task_history(workspace_id,task_id,actor_id,actor_name,action,fields,version)
  VALUES(w,task_id,a.id,a.name,CASE WHEN remove THEN 'deleted' WHEN fresh THEN 'created' ELSE 'updated' END,fields,task.version);
 DELETE FROM public.team_task_history WHERE workspace_id=w AND team_task_history.task_id=task_id AND id NOT IN
  (SELECT id FROM public.team_task_history h WHERE h.workspace_id=w AND h.task_id=task_id ORDER BY created_at DESC,id DESC LIMIT 50);
 RETURN jsonb_build_object('id',task.id,'version',task.version);
END $$;

CREATE FUNCTION public.team_task_history_list(w uuid,t uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w); result jsonb;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.team_tasks WHERE workspace_id=w AND id=t) THEN RAISE EXCEPTION 'Task not found' USING ERRCODE='P0002'; END IF;
 SELECT coalesce(jsonb_agg(x),'[]') INTO result FROM (
  SELECT actor_name AS "actorName",action,fields,version,created_at AS "createdAt" FROM public.team_task_history
   WHERE workspace_id=w AND task_id=t ORDER BY created_at DESC,id DESC LIMIT 50
 ) x; RETURN result;
END $$;

CREATE FUNCTION public.team_task_get(w uuid,t uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w); result jsonb;
BEGIN
 SELECT jsonb_build_object('id',task.id,'title',task.title,'description',task.description,'status',task.status,
  'createdBy',task.created_by,'creatorName',task.creator_name,'assigneeId',task.assignee_id,'assigneeName',a.name,
  'version',task.version,'createdAt',task.created_at,'updatedAt',task.updated_at) INTO result
 FROM public.team_tasks task LEFT JOIN public.auth_users a ON a.id=task.assignee_id
 WHERE task.workspace_id=w AND task.id=t AND task.deleted_at IS NULL;
 IF result IS NULL THEN RAISE EXCEPTION 'Task not found' USING ERRCODE='P0002'; END IF;
 RETURN result;
END $$;

CREATE FUNCTION public.team_invitation_preview(digest text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.auth_users:=public._team_actor(); inv public.team_invitations; result jsonb;
BEGIN
 SELECT * INTO inv FROM public.team_invitations WHERE token_hash=digest AND email=a.email;
 IF NOT FOUND OR inv.canceled_at IS NOT NULL OR inv.expires_at<=clock_timestamp() OR inv.consumed_at IS NOT NULL THEN
  RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE='P0002'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.workspace_members WHERE workspace_id=inv.workspace_id AND user_id=inv.invited_by AND role='owner') THEN
  RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE='P0002'; END IF;
 SELECT jsonb_build_object('projectName',w.name,'invitedBy',u.name,'role',inv.role,'expiresAt',inv.expires_at)
  INTO result FROM public.workspaces w LEFT JOIN public.auth_users u ON u.id=inv.invited_by WHERE w.id=inv.workspace_id;
 RETURN result;
END $$;

CREATE FUNCTION public.team_license_snapshots(w uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p public.team_projects:=public._team_guard(w); result jsonb;
BEGIN
 SELECT coalesce(jsonb_agg(x),'[]') INTO result FROM (
  SELECT environment,price_id,quantity,status,trial_starts_at,trial_ends_at,current_period_starts_at,current_period_ends_at,
   next_billed_at,scheduled_action,scheduled_effective_at,last_occurred_at AS occurred_at,watermark_conflict
  FROM public.billing_subscriptions WHERE workspace_id=p.license_workspace_id ORDER BY last_occurred_at DESC LIMIT 100
 ) x; RETURN result;
END $$;

CREATE FUNCTION public.guard_team_content() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE w uuid; p public.team_projects; policy public.team_policy; used bigint; added bigint;
BEGIN
 w:=CASE WHEN TG_OP='DELETE' THEN OLD.workspace_id ELSE NEW.workspace_id END;
 SELECT * INTO p FROM public.team_projects WHERE workspace_id=w FOR UPDATE;
 IF NOT FOUND THEN RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END; END IF;
 IF TG_OP<>'DELETE' AND NOT public._team_paid(p.license_workspace_id) THEN RAISE EXCEPTION 'Team subscription required' USING ERRCODE='P0001'; END IF;
 SELECT * INTO policy FROM public.team_policy WHERE singleton;
 IF TG_TABLE_NAME='documents' AND TG_OP='INSERT' AND (SELECT count(*) FROM public.documents WHERE workspace_id=w)>=policy.max_documents THEN
  RAISE EXCEPTION 'Project document limit reached' USING ERRCODE='P0003'; END IF;
 IF TG_TABLE_NAME='chunks' AND TG_OP<>'DELETE' THEN
  added:=octet_length(NEW.content)-CASE WHEN TG_OP='UPDATE' THEN octet_length(OLD.content) ELSE 0 END;
  SELECT coalesce(sum(octet_length(content)),0) INTO used FROM public.chunks WHERE workspace_id=w;
  IF used+added>policy.max_content_bytes THEN RAISE EXCEPTION 'Project storage limit reached' USING ERRCODE='P0003'; END IF;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
