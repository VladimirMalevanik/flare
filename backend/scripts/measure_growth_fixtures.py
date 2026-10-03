"""Bounded synthetic acquisition/report/cleanup timings. Never production tuning."""
import json,os,time,statistics
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
from app.models.database import Database
from app.services.attribution_service import AttributionService
from app.services.auth_service import AuthService


def main():
    admin=os.environ['TEST_DATABASE_URL'];db=Database(os.environ['DATABASE_URL']);db.open()
    with psycopg.connect(admin) as c:
        current=c.execute('SELECT current_database()').fetchone()[0]
        assert current==os.environ.get('GROWTH_FIXTURE_DATABASE','flare_growth_test'),'Explicit synthetic disposable database only'
        previous=c.execute('SELECT to_jsonb(p) FROM public.growth_policy p').fetchone()[0]
        c.execute("UPDATE public.growth_policy SET enabled=true,revision='nonproduction-load',notice_id='synthetic',eligibility='explicit-opt-in',cleanup_owner='test',lookback_seconds=60,cookie_seconds=60,raw_seconds=60,linked_seconds=86400,fact_seconds=86400,global_hour=100,network_hour=100,reference_limit=3,visitor_limit=50,budget_limit=100,deadline_ms=500,min_cohort=2,report_window_days=30,report_calendar='UTC-v1',tokens='{}'")
        c.execute('DELETE FROM public.acquisition_visitors');c.execute('DELETE FROM public.acquisition_budgets')
    latencies=[];accepted=0;users=[]
    try:
        collector=AttributionService(db)
        for _ in range(120):
            start=time.perf_counter();ref=collector.touch(reference=None,peer='synthetic-load',touch={'landing_route':'/'},revision='nonproduction-load')
            latencies.append((time.perf_counter()-start)*1000);accepted+=bool(ref)
        auth=AuthService(db)
        for _ in range(20):
            token=auth.register(uuid4().hex+'@growth.invalid','synthetic-long-password','Synthetic')
            users.append(auth.current(token))
        with psycopg.connect(admin) as c:
            c.execute("SET LOCAL statement_timeout='2s'")
            stored=c.execute('SELECT count(*) FROM public.acquisition_visitors').fetchone()[0]
            # Explicit synthetic observation fixture, no provider/domain action claims.
            for user in users:
                logical_id=uuid4()
                for _ in range(2):
                    c.execute("SELECT public.growth_fact(%s,%s,'capture',%s,clock_timestamp(),'manual',1,1)",
                              (user.workspace_id,user.user_id,logical_id))
            start=time.perf_counter();report=c.execute("SELECT public.growth_report(now()-interval '1 day',clock_timestamp(),'account','first')").fetchone()[0];report_ms=(time.perf_counter()-start)*1000
            assert report['metrics']['accounts']==20 and report['metrics']['committed_outcome']==20
            c.execute("UPDATE public.acquisition_visitors SET expires_at=now()-interval '1 second'")
            start=time.perf_counter();cleanup=c.execute('SELECT public.growth_cleanup(50)').fetchone()[0];cleanup_ms=(time.perf_counter()-start)*1000
        print(json.dumps({'nonproduction':True,'requests':120,'global_hour_cap':100,'visitor_cap':50,'accepted':accepted,'stored':stored,
          'touch_median_ms':round(statistics.median(latencies),3),'touch_p95_ms':round(sorted(latencies)[113],3),
          'report_ms':round(report_ms,3),'report_fixture_accounts':20,'report_fixture_deduped_capture_observations':20,
          'report_fixture':'synthetic observations, not production outcomes; no provider calls',
          'cleanup_ms':round(cleanup_ms,3),'cleanup':cleanup,'concurrency':'sequential; DB intake try-lock caps one active transaction'},indent=2))
    finally:
        with psycopg.connect(admin) as c:
            c.execute('UPDATE public.growth_policy SET '+','.join(k+'=%s' for k in previous),tuple(Jsonb(v) if isinstance(v,dict) else v for v in previous.values()))
            c.execute('DELETE FROM public.acquisition_visitors');c.execute('DELETE FROM public.acquisition_budgets')
            for user in users:
                c.execute('DELETE FROM public.auth_users WHERE id=%s',(user.user_id,))
                c.execute('DELETE FROM public.workspace_members WHERE workspace_id=%s',(user.workspace_id,))
                c.execute('DELETE FROM public.workspaces WHERE id=%s',(user.workspace_id,))
        db.close()
if __name__=='__main__':main()
