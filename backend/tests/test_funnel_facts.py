"""Committed facts, domain rollback, terminal completeness and privacy replay."""
from uuid import UUID, uuid4
import psycopg
import pytest
from app.services.item_service import ItemService
from app.services.import_service import ImportService
from app.services.funnel_service import FunnelService
from app.services.analytics_service import AnalyticsService
from test_acquisition import growth
from test_analysis_runs import jobs, admin_url, executor_role, start, service
from test_analysis_jobs import FakeAnalyzer
from test_flare_runs import Detector, stage
from app.services.analysis_jobs import AnalysisProcessor
from app.services.flare_generation import FlareProcessor
from app.config import AISettings
from app.workers.config import WorkerSettings
from app.ai_engine.flare_config import FlareSettings
import asyncio


def facts(e,user):
    with psycopg.connect(e.admin_url) as c:return c.execute('SELECT kind,logical_id FROM public.funnel_facts WHERE workspace_id=%s',(user.workspace_id,)).fetchall()


def test_capture_and_sync_commit_not_best_effort(growth):
    db,e,_,account=growth;u,_=account()
    item=ItemService(db,u.identity).create_note(title='synthetic',content='synthetic')
    importer=ImportService(db,u.identity)
    result=importer.create_import(format='txt',file_name='synthetic.txt',file_type='text/plain',file_size=9,content='synthetic')
    importer.create_import(format='txt',file_name='synthetic.txt',file_type='text/plain',file_size=9,content='synthetic')
    assert sorted(k for k,_ in facts(e,u))==['capture','sync_import']
    with pytest.raises(RuntimeError):
        with db.workspace_transaction(u.identity,write=True) as c:
            c.execute('UPDATE public.documents SET current_version_id=NULL WHERE id=%s',(item.id,))
            c.execute('UPDATE public.documents SET current_version_id=%s WHERE id=%s',(item.current_version_id,item.id))
            raise RuntimeError('rollback')
    assert len(facts(e,u))==2
    FunnelService(db,u.identity).withdraw()
    assert facts(e,u)==[]
    AnalyticsService(db,u.identity).track_event(event_type='capture_started',target_type='capture',metadata={})
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s',(u.user_id,)).fetchone()==(0,)
    ItemService(db,u.identity).create_note(title=None,content='after withdrawal')
    with psycopg.connect(e.admin_url) as c:c.execute('SELECT public.growth_reconcile(100)')
    assert facts(e,u)==[]


@pytest.mark.parametrize('mode,empty',[('manual',False),('manual',True),('scheduled',False)])
def test_both_terminal_manual_mode_preserved_after_cleanup(jobs,admin_url,mode,empty):
    run=start(jobs)
    db=jobs[0].database;identity=jobs[2][0]
    def count():
        with psycopg.connect(admin_url) as c:return c.execute("SELECT logical_id,mode,result_count FROM public.funnel_facts WHERE workspace_id=%s AND kind='analyze'",(identity.workspace_id,)).fetchall()
    assert count()==[]
    if mode=='scheduled':
        with psycopg.connect(admin_url) as c:
            c.execute("UPDATE public.analysis_cycles SET mode='scheduled' WHERE analysis_run_id=%s",(run['id'],))
    asyncio.run(AnalysisProcessor(jobs[1],FakeAnalyzer(),AISettings(),WorkerSettings()).process_one())
    assert count()==[]
    asyncio.run(FlareProcessor(__import__('app.models.flare_runs',fromlist=['FlareRuns']).FlareRuns(jobs[1]._database_url),Detector(empty=empty),AISettings(),FlareSettings(),WorkerSettings()).process_one())
    assert len(count())==1 and count()[0][1]==mode
    with psycopg.connect(admin_url) as c:
        actual=c.execute('SELECT cardinality(g.flare_ids) FROM public.flare_generation_runs g JOIN public.analysis_runs r ON r.analysis_job_id=g.analysis_job_id WHERE r.id=%s',(run['id'],)).fetchone()[0]
    assert count()[0][2]==actual
    if empty:assert actual==0
    before=count()
    with psycopg.connect(admin_url) as c:
        job=c.execute('SELECT analysis_job_id FROM public.analysis_runs WHERE id=%s',(run['id'],)).fetchone()[0]
        c.execute('SELECT public.growth_analyze_fact(%s)',(job,))
        c.execute('DELETE FROM public.analysis_jobs WHERE id=%s',(job,))
    assert count()==before


def test_voluntary_inspection_dedupe_lineage_tenant_and_withdrawal(stage,jobs,admin_url):
    assert asyncio.run(FlareProcessor(stage[0],Detector(),AISettings(),FlareSettings(),WorkerSettings()).process_one())=='completed'
    identity=jobs[2][0];db=jobs[0].database
    with psycopg.connect(admin_url) as c:
        flare=c.execute('SELECT id FROM public.insights WHERE workspace_id=%s',(identity.workspace_id,)).fetchone()[0]
        source=c.execute('SELECT v.document_id FROM public.insight_sources s JOIN public.chunks ch ON ch.id=s.chunk_id JOIN public.document_versions v ON v.id=ch.document_version_id WHERE s.insight_id=%s',(flare,)).fetchone()[0]
    service=FunnelService(db,identity);key=uuid4()
    service.inspect(key,flare,source);service.inspect(key,flare,source)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):FunnelService(db,jobs[2][1]).inspect(uuid4(),flare)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):service.inspect(uuid4(),flare,uuid4())
    with psycopg.connect(admin_url) as c:
        assert c.execute("SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s AND kind='inspection'",(identity.workspace_id,)).fetchone()==(1,)
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE workspace_id=%s AND interaction_id=%s',(identity.workspace_id,key)).fetchone()==(1,)
    service.withdraw(workspace=True);service.inspect(key,flare)
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s',(identity.workspace_id,)).fetchone()==(0,)


from test_import_packages import env, enqueue, checkpoint
from test_zip_import import archive_bytes


def test_zip_gate_out_of_order_commits_reconcile_without_sequence_loss(env):
    e,storage,worker=env;workspace=uuid4();actor='synthetic-zip|'+uuid4().hex
    with e.client(workspace_id=workspace,user_id=actor,import_storage=storage) as client:
        packages=[]
        for value in ('first','second'):
            pid=enqueue(client,archive_bytes([(value+'.txt',value)]))
            job=worker.claim(2);checkpoint(worker,storage,job)
            with psycopg.connect(e.admin_url) as c:
                assert c.execute("SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,)).fetchone()==(len(packages),)
            worker.step(job,'gate');packages.append(pid)
        with psycopg.connect(e.admin_url) as c:
            assert c.execute("SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,)).fetchone()==(2,)
            c.execute('DELETE FROM public.import_publications WHERE workspace_id=%s',(workspace,))
            c.execute("DELETE FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,))
            c.execute('ALTER TABLE public.import_publications DISABLE TRIGGER growth_zip_import')
        a=psycopg.connect(e.admin_url);b=psycopg.connect(e.admin_url)
        try:
            query="INSERT INTO public.import_publications(workspace_id,package_id,requested_by_user_id,source_kind,source_count,chunk_count) SELECT workspace_id,id,requested_by_user_id,source_kind,published_count,chunk_count FROM public.import_packages WHERE id=%s RETURNING id"
            low=a.execute(query,(packages[0],)).fetchone()[0]
            high=b.execute(query,(packages[1],)).fetchone()[0];assert low<high;b.commit()
            with psycopg.connect(e.admin_url) as c:assert c.execute('SELECT public.growth_reconcile(1000)').fetchone()[0]>=1
            a.commit()
            with psycopg.connect(e.admin_url) as c:
                assert c.execute('SELECT public.growth_reconcile(1000)').fetchone()[0]>=1
                c.execute('SELECT public.growth_reconcile(1000)')
                assert c.execute("SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,)).fetchone()==(2,)
                # Expired earlier publications must not starve a newer missing fact.
                c.execute("UPDATE public.import_publications SET published_at=now()-interval '20 days' WHERE package_id=%s",(packages[0],))
                c.execute("UPDATE public.growth_policy SET fact_seconds=864000")
                c.execute("DELETE FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,))
                assert c.execute('SELECT public.growth_reconcile(1)').fetchone()==(1,)
                assert c.execute("SELECT logical_id FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,)).fetchall()==[(UUID(str(packages[1])),)]
        finally:
            a.close();b.close()
            with psycopg.connect(e.admin_url) as c:c.execute('ALTER TABLE public.import_publications ENABLE TRIGGER growth_zip_import')


def test_account_deletion_removes_links_facts_events_and_blocks_replay(growth):
    db,e,_,account=growth;user,_=account()
    ItemService(db,user.identity).create_note(title=None,content='synthetic')
    AnalyticsService(db,user.identity).track_event(event_type='capture_started',target_type='capture',metadata={})
    with psycopg.connect(e.admin_url) as c:
        c.execute('DELETE FROM public.auth_users WHERE id=%s',(user.user_id,))
        c.execute('SELECT public.growth_fact(%s,%s,%s,%s,now(),%s,1,1)',(user.workspace_id,user.user_id,'capture',uuid4(),'manual'))
        c.execute("INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type) VALUES(%s,%s,'capture_started','capture')",(user.workspace_id,user.user_id))
        assert c.execute('SELECT count(*) FROM public.signup_attribution WHERE user_id=%s',(user.user_id,)).fetchone()==(0,)
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',(user.user_id,)).fetchone()==(0,)
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s',(user.user_id,)).fetchone()==(0,)


@pytest.mark.parametrize('outage',['locked','failing'])
def test_zip_publication_does_not_depend_on_growth_consumer_and_reconciles(env,outage):
    e,storage,worker=env;workspace=uuid4();actor='synthetic-isolation|'+uuid4().hex
    with e.client(workspace_id=workspace,user_id=actor,import_storage=storage) as client:
        pid=enqueue(client,archive_bytes([('synthetic.txt','synthetic')]))
        job=worker.claim(2);checkpoint(worker,storage,job)
        blocker=psycopg.connect(e.admin_url)
        try:
            if outage=='locked':
                blocker.execute('LOCK TABLE public.funnel_facts IN ACCESS EXCLUSIVE MODE')
            else:
                blocker.execute("""CREATE FUNCTION public.synthetic_fact_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'synthetic consumer failure'; END $$""")
                blocker.execute('CREATE TRIGGER synthetic_fact_failure BEFORE INSERT ON public.funnel_facts FOR EACH ROW EXECUTE FUNCTION public.synthetic_fact_failure()')
                blocker.commit()
            worker.step(job,'gate')
            assert client.get('/imports/packages/'+pid).json()['status']=='completed'
            assert len(client.get('/items').json())==1
        finally:
            blocker.rollback();blocker.close()
            if outage=='failing':
                with psycopg.connect(e.admin_url) as c:
                    c.execute('DROP TRIGGER synthetic_fact_failure ON public.funnel_facts')
                    c.execute('DROP FUNCTION public.synthetic_fact_failure()')
        with psycopg.connect(e.admin_url) as c:
            assert c.execute("SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,)).fetchone()==(0,)
            assert c.execute('SELECT count(*) FROM public.import_publications WHERE package_id=%s',(pid,)).fetchone()==(1,)
            c.execute('SELECT public.growth_reconcile(1000)')
            c.execute('SELECT public.growth_reconcile(1000)')
            assert c.execute("SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s AND kind='zip_import'",(workspace,)).fetchone()==(1,)
