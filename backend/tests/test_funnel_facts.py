"""Committed facts, domain rollback, terminal completeness and privacy replay."""
from uuid import UUID, uuid4
import os
import psycopg
import pytest
from app.services.item_service import ItemService
from app.services.import_service import ImportService
from app.services.funnel_service import FunnelService
from app.services.analytics_service import AnalyticsService
from test_acquisition import growth, configure, enabled_growth_policy
from test_analysis_runs import jobs, admin_url, executor_role, start, service
from test_analysis_jobs import FakeAnalyzer
from test_flare_runs import Detector, stage
from app.services.analysis_jobs import AnalysisProcessor
from app.services.flare_generation import FlareProcessor
from app.config import AISettings
from app.workers.config import WorkerSettings
from app.ai_engine.flare_config import FlareSettings
import asyncio

pytestmark = pytest.mark.usefixtures('enabled_growth_policy')


def disable_policy(admin, configured):
    # Exercise both the migration default (NULL lifetimes) and stopping collection
    # after configuration. Neither state authorizes new measurement persistence.
    changes = {} if configured else {
        'revision': None, 'notice_id': None, 'eligibility': None, 'cleanup_owner': None,
        'lookback_seconds': None, 'cookie_seconds': None, 'raw_seconds': None,
        'linked_seconds': None, 'fact_seconds': None, 'tokens': {},
    }
    configure(admin, enabled=False, **changes)


@pytest.mark.parametrize('configured', [False, True], ids=['default-null-policy', 'configured-off'])
def test_disabled_policy_keeps_auth_capture_sync_and_legacy_events_without_growth(growth, configured):
    import re
    from app.services.auth_service import AuthService
    db, e, auth, account = growth
    disable_policy(e.admin_url, configured)
    user, _ = account()
    item = ItemService(db, user.identity).create_note(title=None, content='synthetic off-policy capture')
    result = ImportService(db, user.identity).create_import(
        format='txt', file_name='synthetic.txt', file_type='text/plain',
        file_size=9, content='synthetic')
    assert result.batch.status == 'completed'
    AnalyticsService(db, user.identity).track_event(
        event_type='capture_started', target_type='capture', metadata={})

    class Mail:
        def send(self, **kwargs): self.text = kwargs['text']
    mail = Mail()
    verification = AuthService(db, email_verification_required=True, email_sender=mail,
                               app_public_url='http://localhost')
    token = verification.register(uuid4().hex+'@growth.invalid', 'synthetic-long-password', 'Synthetic')
    verified = verification.current(token)
    e.user_ids.add(verified.user_id); e.workspace_ids.add(verified.workspace_id)
    verification.verify_email(re.search(r'token=([A-Za-z0-9_-]+)', mail.text).group(1))
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT verification_provenance FROM public.auth_users WHERE id=%s',
                         (verified.user_id,)).fetchone() == ('actual',)
        assert c.execute('SELECT count(*) FROM public.signup_attribution WHERE user_id=ANY(%s)',
                         ([user.user_id, verified.user_id],)).fetchone() == (0,)
        assert c.execute('SELECT current_version_id FROM public.documents WHERE id=%s',
                         (item.id,)).fetchone()[0] is not None
        assert c.execute("SELECT count(*) FROM public.activity_events WHERE actor_id=%s AND event_type='capture_started'",
                         (user.user_id,)).fetchone() == (1,)
    with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
        assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (0,)
    assert facts(e, user) == []

    # An enabled policy permits bounded historical import reconciliation, never
    # reconstruction of signup linkage or unrecorded capture/inspection actions.
    configure(e.admin_url)
    auth.login(user.email, 'synthetic-long-password')
    with db.workspace_transaction(user.identity) as c:
        c.execute('SELECT public.acquisition_freeze(NULL)')
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.signup_attribution WHERE user_id=%s',
                         (user.user_id,)).fetchone() == (0,)
        assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (1,)
        assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (0,)
    assert [kind for kind, _ in facts(e, user)] == ['sync_import']
    disable_policy(e.admin_url, configured)
    FunnelService(db, user.identity).withdraw()
    configure(e.admin_url)
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (0,)
    assert facts(e, user) == []


@pytest.mark.parametrize('configured', [False, True], ids=['default-null-policy', 'configured-off'])
def test_disabled_policy_keeps_terminal_zip_and_inspection_without_growth(stage, jobs, env, admin_url, configured):
    from app.models.flare_runs import FlareRuns
    with psycopg.connect(admin_url) as c:
        # The shared jobs fixture created captures under its explicit test policy.
        # Isolate this off-policy journey from those earlier setup observations.
        c.execute('DELETE FROM public.funnel_facts WHERE actor_id=ANY(%s)',
                  ([identity.user_id for identity in jobs[2]],))
    disable_policy(admin_url, configured)
    assert asyncio.run(FlareProcessor(stage[0], Detector(), AISettings(),
                                     FlareSettings(), WorkerSettings()).process_one()) == 'completed'
    run = start(jobs)
    identity = jobs[2][0]; db = jobs[0].database
    asyncio.run(AnalysisProcessor(jobs[1], FakeAnalyzer(), AISettings(), WorkerSettings()).process_one())
    assert asyncio.run(FlareProcessor(FlareRuns(jobs[1]._database_url), Detector(),
                                     AISettings(), FlareSettings(), WorkerSettings()).process_one()) == 'completed'
    with psycopg.connect(admin_url) as c:
        flare = c.execute('SELECT id FROM public.insights WHERE source_analysis_job_id=%s',
                          (stage[1],)).fetchone()[0]
        assert c.execute('SELECT status FROM public.analysis_jobs WHERE id=(SELECT analysis_job_id FROM public.analysis_runs WHERE id=%s)',
                         (run['id'],)).fetchone() == ('completed',)
    inspection = FunnelService(db, identity)
    inspection.inspect(uuid4(), flare)
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s AND interaction_id IS NOT NULL',
                         (identity.user_id,)).fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',
                         (identity.user_id,)).fetchone() == (0,)

    e, storage, worker = env; workspace = uuid4(); actor = 'synthetic-off|'+uuid4().hex
    with e.client(workspace_id=workspace, user_id=actor, import_storage=storage) as client:
        pid = enqueue(client, archive_bytes([('synthetic.txt', 'synthetic')]))
        job = worker.claim(2); checkpoint(worker, storage, job); worker.step(job, 'gate')
        assert client.get('/imports/packages/'+pid).json()['status'] == 'completed'
        assert len(client.get('/items').json()) == 1
        with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
            assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (0,)
        with psycopg.connect(admin_url) as c:
            assert c.execute('SELECT count(*) FROM public.import_publications WHERE package_id=%s', (pid,)).fetchone() == (1,)
            assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE workspace_id=%s', (workspace,)).fetchone() == (0,)
        configure(admin_url)
        with psycopg.connect(admin_url) as c:
            assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (1,)
            assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (0,)
        key = uuid4(); inspection.inspect(key, flare); inspection.inspect(key, flare)
        with psycopg.connect(admin_url) as c:
            assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s AND interaction_id IS NOT NULL',
                             (identity.user_id,)).fetchone() == (1,)
            assert c.execute('SELECT kind FROM public.funnel_facts WHERE actor_id=%s',
                             (identity.user_id,)).fetchall() == [('inspection',)]
        disable_policy(admin_url, configured)
        inspection.withdraw(workspace=True)
        configure(admin_url)
        inspection.inspect(uuid4(), flare)
        with psycopg.connect(admin_url) as c:
            assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',
                             (identity.user_id,)).fetchone() == (0,)


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


# Deterministic two-connection schedules: pause a real service after its INSERT,
# prove the other backend is waiting in PostgreSQL, then allow the first COMMIT.
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep


class PrivacyBoundaryDatabase:
    def __init__(self, database, *, paused=False):
        self.database = database
        self.paused = paused
        self.ready, self.release = Event(), Event()
        self.pid = None

    @contextmanager
    def workspace_transaction(self, *args, **kwargs):
        with self.database.workspace_transaction(*args, **kwargs) as c:
            self.pid = c.info.backend_pid
            if not self.paused:
                self.ready.set()
            yield c
            if self.paused:
                self.ready.set()
                if not self.release.wait(5):
                    raise TimeoutError('synthetic transaction release')


class PrivacyWorkerDatabase(PrivacyBoundaryDatabase):
    @contextmanager
    def workspace_transaction(self, *args, **kwargs):
        with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
            self.pid = c.info.backend_pid
            if not self.paused:
                self.ready.set()
            yield c
            if self.paused:
                self.ready.set()
                if not self.release.wait(5):
                    raise TimeoutError('synthetic worker release')


def wait_for_privacy_block(admin, waiter, blocker):
    deadline = monotonic()+2
    with psycopg.connect(admin, autocommit=True) as c:
        while monotonic() < deadline:
            if waiter.pid and blocker.pid in c.execute('SELECT pg_blocking_pids(%s)', (waiter.pid,)).fetchone()[0]:
                return
            sleep(.005)
    raise AssertionError('Expected PostgreSQL transaction lock wait was not observed')


@pytest.mark.parametrize('writer_kind', ['capture', 'event', 'inspection', 'reconcile'])
@pytest.mark.parametrize('removal', ['account', 'workspace', 'expiry'])
@pytest.mark.parametrize('first', ['writer', 'remover'])
def test_privacy_boundary_serializes_real_writers_and_removers(growth, writer_kind, removal, first, request):
    db, e, _, account = growth
    user, _ = account()
    control, _ = account()  # Unrelated tenant must retain its observations.
    ItemService(db, control.identity).create_note(title=None, content='synthetic control')
    flare = None
    if writer_kind == 'inspection':
        from types import SimpleNamespace
        prepared = request.getfixturevalue('stage')
        prepared_jobs = request.getfixturevalue('jobs')
        assert asyncio.run(FlareProcessor(prepared[0],Detector(),AISettings(),FlareSettings(),WorkerSettings()).process_one()) == 'completed'
        identity = prepared_jobs[2][0]
        user = SimpleNamespace(identity=identity,user_id=identity.user_id,workspace_id=identity.workspace_id)
        with psycopg.connect(e.admin_url) as c:
            flare = c.execute('SELECT id FROM public.insights WHERE source_analysis_job_id=%s',(prepared[1],)).fetchone()[0]
            c.execute('DELETE FROM public.funnel_facts WHERE actor_id=%s',(user.user_id,))
            c.execute('DELETE FROM public.activity_events WHERE actor_id=%s',(user.user_id,))
    with psycopg.connect(e.admin_url) as c:
        if removal == 'expiry':
            c.execute("UPDATE public.auth_users SET created_at=clock_timestamp()-interval '20 days' WHERE id=%s", (user.user_id,))
    if writer_kind == 'reconcile':
        result = ImportService(db, user.identity).create_import(format='txt', file_name='synthetic.txt',
            file_type='text/plain', file_size=9, content='synthetic')
        with psycopg.connect(e.admin_url) as c:
            c.execute('DELETE FROM public.funnel_facts WHERE actor_id=%s', (user.user_id,))
            c.execute('DELETE FROM public.activity_events WHERE actor_id=%s', (user.user_id,))
    writer_cls = PrivacyWorkerDatabase if writer_kind == 'reconcile' else PrivacyBoundaryDatabase
    remover_cls = PrivacyWorkerDatabase if removal == 'expiry' else PrivacyBoundaryDatabase
    writer = writer_cls(db, paused=(first == 'writer'))
    remover = remover_cls(db, paused=(first == 'remover'))
    results = {}
    def write():
        if writer_kind == 'capture':
            results['item'] = ItemService(writer,user.identity).create_note(title=None,content='synthetic race capture')
        elif writer_kind == 'event':
            AnalyticsService(writer,user.identity).track_event(event_type='capture_started',target_type='capture',metadata={})
        elif writer_kind == 'inspection':
            FunnelService(writer,user.identity).inspect(uuid4(),flare)
        else:
            with writer.workspace_transaction(user.identity) as c:
                c.execute('SELECT public.growth_reconcile(100)')
    def remove():
        if removal == 'expiry':
            with remover.workspace_transaction(user.identity) as c:
                c.execute('SELECT public.growth_cleanup(100)')
        else:
            FunnelService(remover,user.identity).withdraw(workspace=(removal == 'workspace'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_db, second_db = (writer,remover) if first == 'writer' else (remover,writer)
        first_future = pool.submit(write if first == 'writer' else remove)
        try:
            assert first_db.ready.wait(3), 'First operation did not reach commit boundary'
            if first_future.done(): first_future.result()
            if first == 'writer':
                # The real service returned within the still-open transaction;
                # the observed backend has not reached COMMIT.
                assert writer.pid
            second_future = pool.submit(remove if first == 'writer' else write)
            assert second_db.ready.wait(2)
            wait_for_privacy_block(e.admin_url, second_db, first_db)
            assert not second_future.done()
        finally:
            first_db.release.set()
        first_future.result(timeout=5); second_future.result(timeout=5)
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',(user.user_id,)).fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s',(user.user_id,)).fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',(control.user_id,)).fetchone() == (1,)
        assert c.execute('SELECT count(*) FROM public.auth_users WHERE id=%s',(user.user_id,)).fetchone() == (1,)
        if writer_kind == 'capture':
            assert c.execute('SELECT current_version_id FROM public.documents WHERE id=%s',(results['item'].id,)).fetchone()[0] is not None
        if writer_kind == 'reconcile':
            assert c.execute('SELECT status FROM public.import_batches WHERE id=%s',(result.batch.id,)).fetchone() == ('completed',)
            assert c.execute('SELECT public.growth_reconcile(100)').fetchone() == (0,)


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('first', ['writer', 'delete'])
def test_ordinary_event_account_delete_transaction_boundary(growth, enabled, first):
    db,e,_,account = growth
    configure(e.admin_url,enabled=enabled)
    user,_ = account()
    writer = PrivacyBoundaryDatabase(db,paused=(first == 'writer'))
    deletion = PrivacyBoundaryDatabase(db,paused=(first == 'delete'))
    control,_ = account()
    AnalyticsService(db,control.identity).track_event(event_type='capture_started',target_type='capture',metadata={})
    def write():
        AnalyticsService(writer,user.identity).track_event(event_type='capture_started',target_type='capture',metadata={})
    def delete():
        with psycopg.connect(e.admin_url) as c:
            deletion.pid = c.info.backend_pid
            if first != 'delete': deletion.ready.set()
            c.execute('DELETE FROM public.auth_users WHERE id=%s',(user.user_id,))
            if first == 'delete':
                deletion.ready.set()
                assert deletion.release.wait(5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_db,second_db = (writer,deletion) if first == 'writer' else (deletion,writer)
        a=pool.submit(write if first == 'writer' else delete)
        try:
            assert first_db.ready.wait(3)
            b=pool.submit(delete if first == 'writer' else write)
            assert second_db.ready.wait(2)
            wait_for_privacy_block(e.admin_url,second_db,first_db)
        finally:
            first_db.release.set()
        a.result(timeout=5);b.result(timeout=5)
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.auth_users WHERE id=%s',(user.user_id,)).fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s',(user.user_id,)).fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM public.activity_events WHERE actor_id=%s',(control.user_id,)).fetchone() == (1,)


def test_privacy_removal_rejects_stale_repeatable_read_snapshot(growth):
    db,e,_,account = growth
    user,_ = account()
    with psycopg.connect(e.admin_url) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        c.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",(str(user.workspace_id),user.user_id))
        with pytest.raises(psycopg.errors.RaiseException,match='READ COMMITTED'),c.transaction():
            c.execute('SELECT public.growth_withdraw(false)')
        with pytest.raises(psycopg.errors.RaiseException,match='READ COMMITTED'),c.transaction():
            c.execute('SELECT public.growth_cleanup(100)')



def test_pending_capture_cannot_survive_fact_retention_cleanup(growth):
    db,e,_,account=growth
    user,_=account()
    configure(e.admin_url,fact_seconds=1)  # Explicit synthetic retention only.
    writer=PrivacyBoundaryDatabase(db,paused=True)
    remover=PrivacyWorkerDatabase(db)
    result={}
    def capture():
        result['item']=ItemService(writer,user.identity).create_note(title=None,content='synthetic retained original')
    def cleanup():
        with remover.workspace_transaction() as c:
            c.execute('SELECT public.growth_cleanup(100)')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(capture)
        try:
            assert writer.ready.wait(3)
            # Wait for the actual database retention cutoff while the real
            # observation is pending. Never alter an immutable domain timestamp.
            with psycopg.connect(e.admin_url,autocommit=True) as c:
                cutoff=c.execute("SELECT clock_timestamp()+interval '1 second'").fetchone()[0]
                deadline=monotonic()+2
                while c.execute('SELECT clock_timestamp()>=%s',(cutoff,)).fetchone()==(False,):
                    assert monotonic()<deadline
                    sleep(.01)
            b=pool.submit(cleanup)
            assert remover.ready.wait(2)
            wait_for_privacy_block(e.admin_url,remover,writer)
        finally:
            writer.release.set()
        a.result(timeout=5);b.result(timeout=5)
    with psycopg.connect(e.admin_url) as c:
        assert c.execute('SELECT count(*) FROM public.funnel_facts WHERE actor_id=%s',(user.user_id,)).fetchone()==(0,)
        assert c.execute('SELECT current_version_id FROM public.documents WHERE id=%s',(result['item'].id,)).fetchone()[0] is not None
