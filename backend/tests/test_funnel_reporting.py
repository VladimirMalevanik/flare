from datetime import datetime,timedelta,timezone
from uuid import uuid4
import os
import psycopg
import pytest
from app.services.funnel_service import aggregate_csv
from test_acquisition import growth,configure,touch,enabled_growth_policy


def test_reporting_denied_to_runtime_worker_and_small_cohorts(growth):
    db,e,_,account=growth;user,_=account()
    now=datetime.now(timezone.utc);args=(now-timedelta(days=1),now,'account','first')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.connection() as c:c.execute('SELECT public.growth_report(%s,%s,%s,%s)',args)
    with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT * FROM public.signup_attribution')
    with psycopg.connect(e.admin_url) as c:
        # A narrow synthetic cohort window excludes unrelated test accounts.
        since=c.execute('SELECT created_at FROM public.signup_attribution WHERE user_id=%s',(user.user_id,)).fetchone()[0]
        report=c.execute('SELECT public.growth_report(%s,clock_timestamp(),%s,%s)',(since,'workspace_creator','last')).fetchone()[0]
        assert report['metrics']=={'suppressed':True}
        with pytest.raises(psycopg.errors.RaiseException):c.execute('SELECT public.growth_report(%s,%s,%s,%s)',(now-timedelta(days=31),now,'account','first'))


def test_ordered_actor_milestones_later_day_and_basis(growth):
    db,e,_,account=growth
    users=[account(touch(db,source='alpha'))[0],account(touch(db,source='beta'))[0]]
    now=datetime.now(timezone.utc)
    with psycopg.connect(e.admin_url) as c:
        for u in users:
            c.execute("UPDATE public.auth_users SET created_at=%s,email_verified_at=%s WHERE id=%s",(now-timedelta(days=3),now-timedelta(days=3),u.user_id))
            for kind,day,mode in [('capture',2,'manual'),('analyze',2,'manual'),('inspection',2,'manual'),('inspection',1,'manual')]:
                c.execute('SELECT public.growth_fact(%s,%s,%s,%s,%s,%s,1,1)',(u.workspace_id,u.user_id,kind,uuid4(),now-timedelta(days=day),mode))
        report=c.execute('SELECT public.growth_report(%s,%s,%s,%s)',(now-timedelta(days=4),now,'account','first')).fetchone()[0]
        assert report['metrics']['manual_analyze']>=2 and report['metrics']['later_day_activity']>=2
        assert report['unit']=='account' and report['basis']=='first'
        raw=str(report);assert all(u.user_id not in raw and str(u.workspace_id) not in raw for u in users)


def test_formula_safe_export_only_aggregate_columns():
    report={'revision':'=danger','unit':'@formula','basis':'+evil','calendar':'-evil','metrics':{'accounts':2,'email':'secret','unknown':True}}
    csv=aggregate_csv(report)
    assert "'=danger" in csv and "'@formula" in csv and 'secret' not in csv and 'unknown' not in csv


def test_historical_verification_and_calendar_are_as_of_window_in_utc(growth):
    db,e,_,account=growth
    users=[account()[0],account()[0]]
    since=datetime(2026,1,1,tzinfo=timezone.utc);until=since+timedelta(days=2)
    with psycopg.connect(e.admin_url) as c:
        c.execute("SET LOCAL TIME ZONE 'Pacific/Honolulu'")
        for u in users:
            c.execute("UPDATE public.auth_users SET created_at=%s,verification_provenance='actual',email_verified_at=%s WHERE id=%s",(since+timedelta(hours=23),until+timedelta(hours=1),u.user_id))
        report=c.execute('SELECT public.growth_report(%s,%s,%s,%s)',(since,until,'account','last')).fetchone()[0]
        assert report['metrics']['accounts']==2
        assert report['metrics']['actual_verified']==0 and report['metrics']['verification_unknown']==2
        # The UTC signup day is Jan 1; DB session timezone must not change maturity.
        assert report['metrics']['later_day_observable']==2
        assert report['metrics']['inspection_later_day_observable']==0
        assert 'no all-traffic' in report['visitor_denominator']


def test_failed_snapshot_and_smtp_accounts_count_with_explicit_coverage(growth,monkeypatch):
    from app.services.auth_service import AuthService,EmailDeliveryFailed
    from app.services.item_service import ItemService
    db,e,_,account=growth
    now=datetime.now(timezone.utc)
    monkeypatch.setattr('app.services.attribution_service.reference_digest',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic')))
    user,_=account()
    ItemService(db,user.identity).create_note(title=None,content='synthetic durable account')
    email=uuid4().hex+'@growth.invalid'
    auth=AuthService(db,email_verification_required=True,app_public_url='http://localhost')
    with pytest.raises(EmailDeliveryFailed):auth.register(email,'synthetic-long-password','Synthetic')
    with psycopg.connect(e.admin_url) as c:
        uid,wid=c.execute('SELECT id,initial_workspace_id FROM public.auth_users WHERE email=%s',(email,)).fetchone()
        e.user_ids.add(uid);e.workspace_ids.add(wid)
        report=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','first')",(now,)).fetchone()[0]
        assert report['metrics']['accounts']==2
        assert report['metrics']['snapshot_missing']==2 and report['metrics']['snapshot_present']==0
        assert report['metrics']['bypassed']==1 and report['metrics']['verification_unknown']==1
        assert report['metrics']['committed_outcome']==1
        assert report['attribution'][0]['coverage']=='missing_snapshot'
    # Withdrawal must work even if the initial optional snapshot never existed.
    from app.services.funnel_service import FunnelService
    FunnelService(db,user.identity).withdraw()
    with psycopg.connect(e.admin_url) as c:
        c.execute('SELECT public.growth_fact(%s,%s,%s,%s,now(),%s,1,1)',(user.workspace_id,user.user_id,'capture',uuid4(),'manual'))
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',(user.user_id,)).fetchone()==(0,)


def test_delayed_outcomes_scheduled_completion_and_retries_never_mean_human_return(growth):
    _,e,_,account=growth
    users=[account()[0],account()[0]]
    since=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=4);until=since+timedelta(days=3)
    with psycopg.connect(e.admin_url) as c:
        for u in users:
            c.execute('UPDATE public.auth_users SET created_at=%s,email_verified_at=%s WHERE id=%s',(since,since,u.user_id))
            for kind,hour,mode in [('capture',1,'manual'),('analyze',2,'manual'),('inspection',3,'manual'),
                                   ('zip_import',26,'manual'),('sync_import',27,'manual'),('capture',28,'manual'),
                                   ('analyze',29,'manual'),('analyze',30,'scheduled')]:
                key=uuid4()
                for _ in range(2):c.execute('SELECT public.growth_fact(%s,%s,%s,%s,%s,%s,1,1)',(u.workspace_id,u.user_id,kind,key,since+timedelta(hours=hour),mode))
        before=c.execute("SELECT public.growth_report(%s,%s,'account','first')",(since,until)).fetchone()[0]
        assert before['metrics']['committed_outcome']==2 and before['metrics']['manual_analyze']==2
        assert before['metrics']['voluntary_inspection']==2 and before['metrics']['later_day_activity']==0
        # A retry on tomorrow's delivery retains the original action timestamp and ID.
        for u in users:
            key=c.execute("SELECT logical_id FROM public.funnel_facts WHERE actor_id=%s AND kind='inspection'",(u.user_id,)).fetchone()[0]
            c.execute('SELECT public.growth_fact(%s,%s,%s,%s,%s,%s,0,1)',(u.workspace_id,u.user_id,'inspection',key,since+timedelta(hours=32),'manual'))
        assert c.execute("SELECT public.growth_report(%s,%s,'account','first')",(since,until)).fetchone()[0]['metrics']['later_day_activity']==0
        for u in users:
            c.execute('SELECT public.growth_fact(%s,%s,%s,%s,%s,%s,0,1)',(u.workspace_id,u.user_id,'inspection',uuid4(),since+timedelta(hours=33),'manual'))
        after=c.execute("SELECT public.growth_report(%s,%s,'account','first')",(since,until)).fetchone()[0]
        assert after['metrics']['later_day_activity']==2 and after['human_return_revision']=='human-return-v1'


def test_first_and_last_campaign_buckets_attribute_deduped_outcomes_and_export(growth):
    import csv,io
    from psycopg.types.json import Jsonb
    from app.services.attribution_service import AttributionService
    from test_acquisition import POLICY
    db,e,_,account=growth
    configure(e.admin_url,tokens=POLICY['tokens']|{'utm_campaign':['campaign-a','campaign-b']})
    since=datetime.now(timezone.utc)
    users=[]
    for _ in range(2):
        collector=AttributionService(db)
        reference=collector.touch(reference=None,peer='synthetic',touch={'landing_route':'/','utm_source':'alpha','utm_campaign':'campaign-a'},revision=POLICY['revision'])
        assert collector.touch(reference=reference,peer='synthetic',touch={'landing_route':'/register','utm_source':'beta','utm_campaign':'campaign-b'},revision=POLICY['revision'])==reference
        users.append(account(reference)[0])
    with psycopg.connect(e.admin_url) as c:
        for u in users:
            key=uuid4()
            for _ in range(2):c.execute('SELECT public.growth_fact(%s,%s,%s,%s,clock_timestamp(),%s,1,1)',(u.workspace_id,u.user_id,'zip_import',key,'manual'))
        reports=[c.execute('SELECT public.growth_report(%s,clock_timestamp(),%s,%s)',(since,'account',basis)).fetchone()[0] for basis in ('first','last')]
        first,last=reports
        assert first['metrics']==last['metrics'] and first['metrics']['committed_outcome']==2
        assert len(first['attribution'])==len(last['attribution'])==1
        assert (first['attribution'][0]['source'],first['attribution'][0]['campaign'])==('alpha','campaign-a')
        assert (last['attribution'][0]['source'],last['attribution'][0]['campaign'])==('beta','campaign-b')
        assert first['attribution'][0]['metrics']['committed_outcome']==last['attribution'][0]['metrics']['committed_outcome']==2
        exported=list(csv.DictReader(io.StringIO(aggregate_csv(last))))
        assert any(row['row_type']=='attribution' and row['campaign']=='campaign-b' and row['metric']=='committed_outcome' and row['count']=='2' for row in exported)
        # One tiny bucket suppresses the whole breakdown, including complementary cells.
        user,_=account(touch(db,source='alpha'))
        suppressed=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','last')",(since,)).fetchone()[0]
        assert suppressed['attribution_suppressed'] and suppressed['attribution'] is None
        assert all(row['row_type']=='total' for row in csv.DictReader(io.StringIO(aggregate_csv(suppressed))))


@pytest.mark.parametrize('zone',['UTC','Europe/Moscow'])
def test_near_midnight_report_calendar_and_return_are_explicit_utc(growth,zone):
    _,e,_,account=growth
    users=[account()[0],account()[0]]
    since=datetime.now(timezone.utc).replace(hour=23,minute=30,second=0,microsecond=0)-timedelta(days=3)
    until=since+timedelta(hours=1)
    with psycopg.connect(e.admin_url) as c:
        c.execute("SELECT set_config('TimeZone',%s,true)",(zone,))
        for u in users:
            c.execute('UPDATE public.auth_users SET created_at=%s,email_verified_at=%s WHERE id=%s',(since,since,u.user_id))
            for kind,minute in [('capture',1),('analyze',2),('inspection',3),('inspection',35)]:
                c.execute('SELECT public.growth_fact(%s,%s,%s,%s,%s,%s,1,1)',(u.workspace_id,u.user_id,kind,uuid4(),since+timedelta(minutes=minute),'manual'))
        report=c.execute("SELECT public.growth_report(%s,%s,'account','first')",(since,until)).fetchone()[0]
        assert report['calendar']=='UTC-v1'
        assert report['metrics']['later_day_observable']==report['metrics']['inspection_later_day_observable']==2
        assert report['metrics']['later_day_activity']==2


def test_attribution_export_formula_safety_and_disclosure():
    import csv,io
    bucket={'coverage':'eligible_non_direct','source':'=formula','campaign':'@command','metrics':{'accounts':2,'email':'private'}}
    report={'attribution':[bucket],'attribution_suppressed':False}
    rows=list(csv.DictReader(io.StringIO(aggregate_csv(report))))
    assert rows[0]['source']=="'=formula" and rows[0]['campaign']=="'@command"
    assert 'private' not in aggregate_csv(report)
    report['attribution_suppressed']=True
    assert len(list(csv.DictReader(io.StringIO(aggregate_csv(report)))))==0


def test_restricted_reporter_has_only_aggregate_capability_and_runtime_is_denied(growth):
    db,e,_,account=growth
    users=[account()[0],account()[0]]
    since=datetime.now(timezone.utc)-timedelta(minutes=1)
    with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','first')",(since,))
    with psycopg.connect(e.admin_url) as c:
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='flare_growth_reporter'").fetchone():
            c.execute('CREATE ROLE flare_growth_reporter NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE')
        c.execute('GRANT EXECUTE ON FUNCTION public.growth_report(timestamptz,timestamptz,text,text) TO flare_growth_reporter')
        c.execute('SET LOCAL ROLE flare_growth_reporter')
        report=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'workspace_creator','last')",(since,)).fetchone()[0]
        assert report['metrics']['accounts']==2
        for table in ('auth_users','signup_attribution','funnel_facts','acquisition_visitors'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege),c.transaction():
                c.execute('SELECT * FROM public.'+table)
        with pytest.raises(psycopg.errors.InsufficientPrivilege),c.transaction():
            c.execute('SELECT public.growth_reconcile(1)')
        with pytest.raises(psycopg.errors.RaiseException),c.transaction():
            c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','invented')",(since,))
        c.rollback()


def test_direct_unlinked_and_missing_snapshot_remain_distinct(growth,monkeypatch):
    db,e,_,account=growth
    since=datetime.now(timezone.utc)
    for _ in range(2):account(touch(db))
    for _ in range(2):account()
    monkeypatch.setattr('app.services.attribution_service.reference_digest',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic')))
    for _ in range(2):account()
    with psycopg.connect(e.admin_url) as c:
        report=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','last')",(since,)).fetchone()[0]
        assert report['metrics']['accounts']==6 and report['metrics']['eligible']==2 and report['metrics']['unknown']==4
        assert report['metrics']['snapshot_missing']==2
        assert {x['coverage'] for x in report['attribution']}=={'eligible_direct_or_unknown','unlinked_unknown','missing_snapshot'}
        assert all(x['metrics']['accounts']==2 for x in report['attribution'])


def test_attribution_output_cardinality_is_bounded_without_partial_disclosure(growth):
    from psycopg.types.json import Jsonb
    from test_acquisition import POLICY
    _,e,_,_=growth
    campaigns=['fixture-'+str(n) for n in range(101)]
    configure(e.admin_url,tokens=POLICY['tokens']|{'utm_campaign':campaigns})
    since=datetime.now(timezone.utc)
    with psycopg.connect(e.admin_url) as c:
        for campaign in campaigns:
            for _ in range(2):
                uid='synthetic-cardinality|'+uuid4().hex;wid=uuid4()
                e.user_ids.add(uid);e.workspace_ids.add(wid)
                c.execute('INSERT INTO public.workspaces(id,name) VALUES(%s,%s)',(wid,'Synthetic'))
                c.execute('INSERT INTO public.auth_users(id,email,password_hash,name,initial_workspace_id) VALUES(%s,%s,%s,%s,%s)',(uid,uuid4().hex+'@growth.invalid','unusable-synthetic-hash','Synthetic',wid))
                c.execute('INSERT INTO public.signup_attribution(user_id,workspace_id,created_at,eligibility,finalized,first_touch) VALUES(%s,%s,clock_timestamp(),%s,true,%s)',(uid,wid,'eligible',Jsonb({'landing_route':'/','utm_campaign':campaign})))
        # The auth timestamp is authoritative, even if snapshot insertion is later.
        c.execute('UPDATE public.auth_users SET created_at=%s WHERE id=ANY(%s)',(since,list(e.user_ids)))
        report=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','first')",(since,)).fetchone()[0]
        assert report['metrics']['accounts']==202 and report['attribution_bucket_limit']==100
        assert report['attribution_suppressed'] and report['attribution'] is None


@pytest.mark.parametrize('policy_state', ['enabled','disabled','absent','null-cohort','zero-cohort','null-window','zero-window','invalid-calendar','null-revision','null-notice','null-cleanup','invalid-eligibility','null-retention'])
def test_same_small_cohort_fails_closed_for_restricted_report_and_csv(growth,policy_state):
    import csv,io
    _,e,_,account=growth
    user,_=account()
    with psycopg.connect(e.admin_url) as c:
        since=c.execute('SELECT created_at FROM public.auth_users WHERE id=%s',(user.user_id,)).fetchone()[0]
        # Changes are rolled back. Simulate damaged configuration only in the
        # disposable test transaction, without relaxing production constraints.
        if policy_state == 'disabled': c.execute('UPDATE public.growth_policy SET enabled=false')
        elif policy_state == 'absent': c.execute('DELETE FROM public.growth_policy')
        elif policy_state != 'enabled':
            checks=c.execute("SELECT conname FROM pg_constraint WHERE conrelid='public.growth_policy'::regclass AND contype='c'").fetchall()
            from psycopg import sql
            for (name,) in checks:
                c.execute(sql.SQL('ALTER TABLE public.growth_policy DROP CONSTRAINT {}').format(sql.Identifier(name)))
            updates={'null-cohort':('min_cohort',None),'zero-cohort':('min_cohort',0),
                'null-window':('report_window_days',None),'zero-window':('report_window_days',0),
                'invalid-calendar':('report_calendar','unapproved'),'null-revision':('revision',None),
                'null-notice':('notice_id',None),'null-cleanup':('cleanup_owner',None),
                'invalid-eligibility':('eligibility','unapproved'),'null-retention':('fact_seconds',None)}
            column,value=updates[policy_state]
            c.execute(sql.SQL('UPDATE public.growth_policy SET {}=%s').format(sql.Identifier(column)),(value,))
        c.execute('GRANT EXECUTE ON FUNCTION public.growth_report(timestamptz,timestamptz,text,text) TO flare_growth_reporter')
        c.execute('SET LOCAL ROLE flare_growth_reporter')
        assert not c.execute("SELECT has_table_privilege(current_user,'public.auth_users','SELECT')").fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege),c.transaction():
            c.execute('SELECT id FROM public.auth_users')
        if policy_state == 'enabled':
            report=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','first')",(since,)).fetchone()[0]
            assert report['metrics']=={'suppressed':True}
            assert list(csv.DictReader(io.StringIO(aggregate_csv(report))))==[]
        else:
            # The CSV export path first obtains the restricted SQL report. No
            # report is available to serialize when required policy is missing.
            with pytest.raises(psycopg.errors.RaiseException,match='Reporting policy/window required'),c.transaction():
                report=c.execute("SELECT public.growth_report(%s,clock_timestamp(),'account','first')",(since,)).fetchone()[0]
                aggregate_csv(report)
        c.rollback()
