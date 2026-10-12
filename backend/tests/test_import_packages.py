"""Full session/API/storage/PostgreSQL/worker/gate tests using restricted runtime roles."""
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID,uuid4
import io
import psycopg
import pytest
from psycopg.types.json import Jsonb
from app.import_staging import LocalStagedObjects
from app.import_staging.policy import ImportPolicy
from app.models.import_packages import ImportWorkerJobs,ImportPackageError
from app.workers.import_worker import ImportProcessor
from test_items_api import ApiEnvironment
from test_zip_import import archive_bytes

pytestmark=pytest.mark.integration


@pytest.fixture
def env(tmp_path):
    if not all(os.getenv(key) for key in ('DATABASE_URL','TEST_DATABASE_URL','WORKER_DATABASE_URL')):
        pytest.skip('Disposable migrated database required')
    environment=ApiEnvironment(os.environ['DATABASE_URL'],os.environ['TEST_DATABASE_URL'])
    storage=LocalStagedObjects(tmp_path/'private')
    jobs=ImportWorkerJobs(os.environ['WORKER_DATABASE_URL'])
    try: yield environment,storage,jobs
    finally: environment.cleanup()


def session(client,raw,kind='obsidian',key=None):
    r=client.post('/imports/packages',json={'sourceKind':kind,'fileName':'snapshot.zip','fileSize':len(raw),'requestKey':str(key or uuid4())})
    assert r.status_code==201,r.text
    id=r.json()['id']
    r=client.put(f'/imports/packages/{id}/upload',content=raw,headers={'Content-Type':'application/octet-stream'})
    assert r.status_code==200,r.text
    return id


def enqueue(client,raw,kind='obsidian'):
    id=session(client,raw,kind)
    r=client.post(f'/imports/packages/{id}/finalize')
    assert r.status_code==200,r.text
    return r.json()['id']


def admin(env,query,args=()):
    with psycopg.connect(env.admin_url) as c:
        row=c.execute(query,args)
        return row.fetchall() if row.description else None


def checkpoint(jobs,storage,job):
    processor=ImportProcessor(jobs,storage)
    with storage.reader(job['object_key']) as source:
        manifest=processor.decode(job,source,'manifest')['manifest']
        jobs.step(job,'manifest',manifest)
        for row in manifest:
            result=processor.decode(job,source,'file',row['ordinal'])
            jobs.step(job,'entry',result)
            if result['parsed']['status']=='prepared': jobs.step(job,'publish',{'ordinal':row['ordinal']})


@pytest.mark.parametrize('kind',['notion','obsidian'])
def test_end_to_end_gate_provenance_exact_retry_no_ai(env,kind,monkeypatch):
    e,storage,jobs=env
    # Import must never get as far as any provider, even after publication.
    monkeypatch.setattr('app.ai_engine.groq_adapter.GroqTextAnalyzer.analyze',lambda *a,**kw: pytest.fail('Import invoked AI'))
    raw=archive_bytes([('folder/Idea.md','---\nkind: note\n---\n# Research\nПривет 👋\n'),('other/Idea.txt','second source'),('sheet.csv','a,b\n"multiline\nrow","a,b"\n'),('.obsidian/config.json','{}'),('asset.pdf',b'\x00binary')])
    ws,user=uuid4(),'import|'+uuid4().hex
    with e.client(workspace_id=ws,user_id=user,import_storage=storage) as client:
        id=enqueue(client,raw,kind)
        job=jobs.claim(2)
        assert job['id']==id
        checkpoint(jobs,storage,job)
        entries=client.get(f'/imports/packages/{id}/entries').json()['entries']
        docs=[entry['document_id'] for entry in entries if entry['document_id']]
        assert len(docs)==3
        assert client.get('/items').json()==[]
        assert all(client.get('/items/'+doc).status_code==404 for doc in docs)
        with psycopg.connect(e.runtime_url) as c:
            c.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",(str(ws),user))
            for table in ('documents','document_versions','chunks'):
                assert c.execute(f'SELECT count(*) FROM public.{table}').fetchone()==(0,)
        # Privileged worker snapshots use ready + current-version joins.
        assert admin(e,"SELECT count(*) FROM documents d JOIN document_versions v ON v.id=d.current_version_id WHERE d.workspace_id=%s AND v.state='ready'",(ws,))==[(0,)]
        assert admin(e,"SELECT count(*) FROM document_versions WHERE workspace_id=%s AND state='ready'",(ws,))==[(0,)]
        jobs.step(job,'gate')
        result=client.get(f'/imports/packages/{id}').json()
        assert result['status']=='completed_with_skips' and result['published_count']==3 and result['skipped_count']==2
        items=client.get('/items').json()
        assert len(items)==3
        assert all(item['relativePath'] and item['importPackageId']==id for item in items)
        assert len([item for item in items if item['title']=='Idea'])==2
        assert client.get('/imports/packages/publications').json()['publications'][0]['package_id']==id
        assert admin(e,'SELECT count(*) FROM analysis_jobs WHERE workspace_id=%s',(ws,))==[(0,)]
        assert admin(e,'SELECT count(*) FROM analysis_daily_quotas WHERE workspace_id=%s',(ws,))==[(0,)]
        assert admin(e,'SELECT count(*) FROM analysis_runs WHERE workspace_id=%s',(ws,))==[(0,)]
        with pytest.raises(ImportPackageError,match='lease_lost'): jobs.step(job,'gate')
        # Deletion/editing never invalidates accepted-package deduplication.
        client.delete('/items/'+docs[0])
        retry=enqueue(client,raw,kind)
        assert retry==id and len(client.get('/items').json())==2
        assert len(client.get('/imports/packages/publications').json()['publications'])==1
        assert ImportProcessor(jobs,storage).cleanup_one()=='deleted'
        assert not list(storage.root.glob('*.zip')) or len(list(storage.root.glob('*.zip')))==1


def test_worker_full_path_no_supported_and_bad_integrity_fail_closed(env):
    e,storage,jobs=env
    with e.client(import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('paper.pdf',b'asset')]))
        assert ImportProcessor(jobs,storage).process_one()=='failed'
        assert client.get(f'/imports/packages/{id}').json()['error_code']=='no_supported_content_or_incomplete'
        assert client.get('/items').json()==[]
        id=enqueue(client,archive_bytes([('../unsafe.md','private content')]))
        assert ImportProcessor(jobs,storage).process_one()=='failed'
        assert client.get(f'/imports/packages/{id}').json()['error_code']=='unsafe_path'
        assert client.get('/items').json()==[]


def test_restart_stale_lease_and_checkpoint_idempotency(env):
    e,storage,jobs=env
    raw=archive_bytes([('nested/a.md','one'),('nested/b.md','two')])
    with e.client(import_storage=storage) as client:
        id=enqueue(client,raw)
        first=jobs.claim(2)
        checkpoint(jobs,storage,first)
        admin(e,"UPDATE import_packages SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(UUID(id),))
        second=jobs.claim(2)
        assert second['generation']>first['generation']
        with pytest.raises(ImportPackageError,match='lease_lost'): jobs.step(first,'gate')
        assert jobs.step(second,'next')=={'gate':True}
        jobs.step(second,'gate')
        assert len(client.get('/items').json())==2
        assert admin(e,'SELECT count(*) FROM import_publications WHERE package_id=%s',(UUID(id),))==[(1,)]


def test_cancel_fences_worker_and_durable_cleanup(env):
    e,storage,jobs=env
    with e.client(import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('a.md','hello')]))
        job=jobs.claim(2); checkpoint(jobs,storage,job)
        assert client.post(f'/imports/packages/{id}/cancel').status_code==200
        with pytest.raises(ImportPackageError,match='lease_lost'): jobs.step(job,'gate')
        assert client.get('/items').json()==[]
        processor=ImportProcessor(jobs,storage)
        original=storage.delete
        storage.delete=lambda key: (_ for _ in ()).throw(OSError('test'))
        assert processor.cleanup_one()=='cleanup_retry'
        storage.delete=original
        admin(e,'UPDATE import_objects SET available_at=now() WHERE package_id=%s',(UUID(id),))
        assert processor.cleanup_one()=='deleted'
        assert not list(storage.root.glob('*.zip')) and not list(storage.root.glob('*.part'))
        assert admin(e,'SELECT count(*) FROM documents WHERE import_package_id=%s',(UUID(id),))==[(0,)]


def test_concurrent_finalize_exact_package_is_one_job(env):
    e,storage,jobs=env
    ws,user=uuid4(),'concurrent|'+uuid4().hex
    raw=archive_bytes([('a.md','hello')])
    with e.client(workspace_id=ws,user_id=user,import_storage=storage) as client:
        one=session(client,raw); two=session(client,raw)
        with ThreadPoolExecutor(2) as pool:
            responses=list(pool.map(lambda id:client.post(f'/imports/packages/{id}/finalize'),[one,two]))
        assert all(r.status_code==200 for r in responses)
        assert responses[0].json()['id']==responses[1].json()['id']
        assert ImportProcessor(jobs,storage).process_one()=='completed'
        assert len(client.get('/items').json())==1


def test_quota_reservation_race_and_viewer_tenant_isolation(env):
    e,storage,jobs=env
    ws,user=uuid4(),'quota|'+uuid4().hex
    raw=archive_bytes([('a.md','hello')])
    policy=replace(ImportPolicy(),staged_quota_bytes=len(raw),workspace_concurrency=3)
    with e.client(workspace_id=ws,user_id=user,import_storage=storage,import_policy=policy) as client:
        payload=lambda:{'sourceKind':'notion','fileName':'a.zip','fileSize':len(raw),'requestKey':str(uuid4())}
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:client.post('/imports/packages',json=payload()),range(2)))
        assert sorted(r.status_code for r in results)==[201,413]
        id=next(r.json()['id'] for r in results if r.status_code==201)
        with e.client(import_storage=storage) as other:
            assert other.get(f'/imports/packages/{id}').status_code==404
            assert other.post(f'/imports/packages/{id}/cancel').status_code==404
        admin(e,"UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(ws,user))
        assert client.post(f'/imports/packages/{id}/cancel').status_code==403
        assert client.post('/imports/packages',json=payload()).status_code==403


def test_authorization_revocation_and_cleanup_before_gate(env):
    e,storage,jobs=env
    ws,user=uuid4(),'revoked|'+uuid4().hex
    with e.client(workspace_id=ws,user_id=user,import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('a.md','hello')]))
        job=jobs.claim(2); checkpoint(jobs,storage,job)
        admin(e,"UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(ws,user))
        with pytest.raises(ImportPackageError,match='authorization_revoked'): jobs.step(job,'gate')
        admin(e,'UPDATE import_objects SET expires_at=now() WHERE package_id=%s',(UUID(id),))
        assert ImportProcessor(jobs,storage).cleanup_one()=='deleted'
        assert client.get('/items').json()==[]


def test_upload_disconnect_deadline_and_resume_cleanup(env):
    e,storage,jobs=env
    with e.client(import_storage=storage) as client:
        raw=archive_bytes([('a.md','hello')])
        r=client.post('/imports/packages',json={'sourceKind':'notion','fileName':'a.zip','fileSize':len(raw),'requestKey':str(uuid4())})
        id=r.json()['id']
        response=client.put(f'/imports/packages/{id}/upload',content=b'not complete',headers={'Content-Type':'application/octet-stream'})
        assert response.status_code==409
        assert client.get(f'/imports/packages/{id}').json()['status']=='failed'
        admin(e,'UPDATE import_objects SET expires_at=now() WHERE package_id=%s',(UUID(id),))
        assert ImportProcessor(jobs,storage).cleanup_one()=='deleted'


def test_restricted_worker_and_readiness_inventory(env):
    e,storage,jobs=env
    from app.models.database import database_is_ready
    assert database_is_ready(e.runtime_url)
    with pytest.raises(ValueError,match='restricted'): ImportWorkerJobs(e.runtime_url)
    with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege): c.execute('SELECT * FROM import_packages')


def test_cancel_publish_race_has_exactly_one_terminal_outcome(env):
    e,storage,jobs=env
    with e.client(import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('a.md','atomic')]))
        job=jobs.claim(2);checkpoint(jobs,storage,job)
        def publish():
            try:return jobs.step(job,'gate')
            except ImportPackageError as error:return error.code
        with ThreadPoolExecutor(2) as pool:
            gate=pool.submit(publish);cancel=pool.submit(client.post,f'/imports/packages/{id}/cancel')
            gate.result();cancel.result()
        result=client.get(f'/imports/packages/{id}').json()
        assert result['status'] in {'completed','cancelled'}
        assert len(client.get('/items').json())==(1 if result['status']=='completed' else 0)
        assert admin(e,'SELECT count(*) FROM import_publications WHERE package_id=%s',(UUID(id),))==[(1 if result['status']=='completed' else 0,)]


def test_source_quota_chunks_bound_failed_file_and_recovery_retry(env):
    e,storage,jobs=env
    policy=replace(ImportPolicy(),source_quota_bytes=4)
    with e.client(import_storage=storage,import_policy=policy) as client:
        id=enqueue(client,archive_bytes([('a.md','too much content')]))
        assert ImportProcessor(jobs,storage).process_one()=='failed'
        result=client.get(f'/imports/packages/{id}').json()
        assert result['failed_count']==1 and result['error_code']=='source_quota'
        assert client.get('/items').json()==[]
    with e.client(import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('a.md','restart safely')]))
        job=jobs.claim(2)
        with pytest.raises(ImportPackageError,match='storage_or_worker_unavailable'):
            jobs.step(job,'transient',{'code':'storage_or_worker_unavailable'})
        assert client.get(f'/imports/packages/{id}').json()['status']=='retry_wait'
        admin(e,"UPDATE import_packages SET available_at=now() WHERE id=%s",(UUID(id),))
        assert ImportProcessor(jobs,storage).process_one()=='completed'
        assert len(client.get('/items').json())==1


def test_package_gate_excludes_real_search_export_manual_and_scheduled_selection(env):
    e,storage,jobs=env
    from app.config import AISettings
    from app.models.database import Database,WorkspaceIdentity
    from app.models.analysis_runs import AnalysisRuns,NoEligibleContext
    from datetime import date,datetime,timezone,timedelta
    import zipfile,json
    ws,user=uuid4(),'readers|'+uuid4().hex
    with e.client(workspace_id=ws,user_id=user,import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('secret.md','gated source evidence')]))
        job=jobs.claim(2);checkpoint(jobs,storage,job)
        assert client.get('/items?query=gated').json()==[]
        export=client.get('/export');assert export.status_code==200
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            assert json.loads(archive.read('raw/export.json'))['notes']==[]
        database=Database(e.runtime_url);database.open()
        try:
            with database.workspace_transaction(WorkspaceIdentity(ws,user),write=True) as c:
                with pytest.raises(NoEligibleContext):AnalysisRuns.start(c,WorkspaceIdentity(ws,user),uuid4(),AISettings(),'test','test',3)
        finally:database.close()
        # Seed only a disposable refresh cycle; invoke the real restricted
        # scheduled candidate function without enqueuing Analyze/provider work.
        cycle,token=uuid4(),uuid4()
        admin(e,"""INSERT INTO analysis_cycles(id,workspace_id,requested_by_user_id,local_date,scheduled_for,idempotency_key,mode,refresh_due_at,refresh_status,refresh_lease_owner,refresh_lease_token,refresh_lease_expires_at)
           VALUES(%s,%s,%s,%s,%s,%s,'scheduled',now(),'refreshing',gen_random_uuid(),%s,now()+interval '1 minute')""",
           (cycle,ws,user,date.today(),datetime.now(timezone.utc),uuid4(),token))
        # Seeding a scheduled cycle itself reserves a day through its existing
        # trigger. The import must leave that fixture-created quota unchanged.
        before=admin(e,'SELECT count(*) FROM analysis_daily_quotas WHERE workspace_id=%s',(ws,))
        with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
            result=c.execute('SELECT load_analysis_cycle_candidates(%s,%s,10,10000)',(cycle,token)).fetchone()[0]
            assert result.get('candidates')==[]
        jobs.step(job,'gate')
        assert len(client.get('/items?query=gated').json())==1
        with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
            result=c.execute('SELECT load_analysis_cycle_candidates(%s,%s,10,10000)',(cycle,token)).fetchone()[0]
            assert len(result['candidates'])==1
        assert admin(e,'SELECT count(*) FROM analysis_daily_quotas WHERE workspace_id=%s',(ws,))==before


def test_api_capability_and_production_boundary(env,monkeypatch):
    e,storage,jobs=env
    with e.client() as client:
        assert client.get('/imports/packages/capabilities').json()=={'available':False,'maxUploadBytes':None}
        response=client.post('/imports/packages',json={'sourceKind':'notion','fileName':'a.zip','fileSize':100,'requestKey':str(uuid4())})
        assert response.status_code==503
    from app.main import create_app
    from app.config import Settings,load_settings
    with pytest.raises(ValueError,match='Local ZIP staging'):create_app(Settings(database_url=None,cors_origins=[]),import_storage=storage)
    monkeypatch.setenv('FLARE_ENV','test');monkeypatch.setenv('FLARE_IMPORT_STAGING_ROOT',str(storage.root))
    assert load_settings().import_staging_root==str(storage.root)


def test_bounded_full_application_load_fixture(env):
    import time,json,platform,hashlib
    e,storage,jobs=env
    count=30
    body=''.join(hashlib.sha256(str(i).encode()).hexdigest()+'\n' for i in range(60))
    raw=archive_bytes([(f'folder/note-{i}.md',body) for i in range(count)])
    with e.client(import_storage=storage) as client:
        started=time.perf_counter();id=enqueue(client,raw);queued=time.perf_counter()
        assert ImportProcessor(jobs,storage).process_one()=='completed'
        published=time.perf_counter()
        result=client.get(f'/imports/packages/{id}').json()
        assert result['published_count']==count and result['prepared_count']==count
        items=client.get('/items?limit=50').json()
        assert len(items)==count and all(item['content']==body for item in items)
        assert ImportProcessor(jobs,storage).cleanup_one()=='deleted'
        ended=time.perf_counter()
        evidence={'purpose':'Synthetic local/test application evidence; not production quota tuning',
            'platform':platform.platform(),'databaseMode':os.getenv('FLARE_DATABASE_PROVIDER'),
            'entries':count,'compressedBytes':len(raw),'expandedBytes':len(body.encode())*count,
            'publishedSources':count,'queuedSeconds':round(queued-started,4),
            'workerThroughGateSeconds':round(published-queued,4),'cleanupAndReadSeconds':round(ended-published,4),
            'limitations':'Single synthetic workspace, local staging, local PostgreSQL17; excludes Azure/network/concurrent load.'}
        if os.getenv('ZIP_IMPORT_LOAD_EVIDENCE'):
            from pathlib import Path
            Path(os.environ['ZIP_IMPORT_LOAD_EVIDENCE']).write_text(json.dumps(evidence,indent=2)+'\n')


def test_global_concurrency_is_server_policy_even_if_caller_requests_more(env):
    e,storage,jobs=env
    clients=[]
    from contextlib import ExitStack
    with ExitStack() as stack:
        for index in range(3):
            client=stack.enter_context(e.client(import_storage=storage))
            enqueue(client,archive_bytes([('a.md',f'workspace {index}')]))
        first=jobs.claim(1000);second=jobs.claim(1000)
        assert first and second
        assert jobs.claim(1000) is None


def test_exhausted_leases_and_deadlines_cannot_publish(env):
    e,storage,jobs=env
    with e.client(import_storage=storage,import_policy=replace(ImportPolicy(),attempts=1)) as client:
        id=enqueue(client,archive_bytes([('a.md','hello')]))
        first=jobs.claim(2)
        admin(e,"UPDATE import_packages SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(UUID(id),))
        assert jobs.claim(2)=={'expired':True}
        assert client.get(f'/imports/packages/{id}').json()['status']=='failed'
        with pytest.raises(ImportPackageError,match='lease_lost'):jobs.step(first,'gate')
        assert client.get('/items').json()==[]
    with e.client(import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('a.md','deadline')]))
        job=jobs.claim(2)
        admin(e,"UPDATE import_packages SET job_deadline=now()-interval '1 second' WHERE id=%s",(UUID(id),))
        with pytest.raises(ImportPackageError,match='job_deadline'):jobs.step(job,'heartbeat')
        assert client.get(f'/imports/packages/{id}').json()['error_code']=='job_deadline'


def test_cleanup_fencing_and_expired_unstarted_session_release_reservation(env):
    e,storage,jobs=env
    with e.client(import_storage=storage) as client:
        raw=archive_bytes([('a.md','hello')]);id=enqueue(client,raw)
        assert ImportProcessor(jobs,storage).process_one()=='completed'
        first=jobs.cleanup()
        admin(e,"UPDATE import_objects SET cleanup_expires_at=now()-interval '1 second' WHERE key=%s",(first['key'],))
        second=jobs.cleanup();assert second['cleanup_token']!=first['cleanup_token']
        with pytest.raises(ImportPackageError,match='lease_lost'):jobs.cleanup('done',first['key'],first['cleanup_token'])
        storage.delete(second['key']);jobs.cleanup('done',second['key'],second['cleanup_token'])
        session=client.post('/imports/packages',json={'sourceKind':'obsidian','fileName':'a.zip','fileSize':len(raw),'requestKey':str(uuid4())}).json()
        admin(e,"UPDATE import_packages SET expires_at=now()-interval '1 second' WHERE id=%s",(UUID(session['id']),))
        assert jobs.cleanup() is None
        assert client.get('/imports/packages/'+session['id']).json()['status']=='expired'


def test_retry_now_accelerates_retry_wait_without_a_duplicate_session(env):
    e,storage,jobs=env
    with e.client(import_storage=storage) as client:
        id=enqueue(client,archive_bytes([('a.md','recover')]))
        job=jobs.claim(2)
        with pytest.raises(ImportPackageError):jobs.step(job,'transient',{'code':'storage_or_worker_unavailable'})
        r=client.post('/imports/packages/'+id+'/retry')
        assert r.status_code==200 and r.json()['id']==id
        assert ImportProcessor(jobs,storage).process_one()=='completed'
        assert len(client.get('/items').json())==1


@pytest.mark.parametrize('changed', [
    {'sourceKind': 'notion'}, {'fileName': 'different.zip'}, {'fileSize': 101},
])
def test_create_request_key_binds_accepted_identity_without_side_effects(env, changed):
    e, storage, jobs = env
    ws, user = uuid4(), 'identity|' + uuid4().hex
    payload = {'sourceKind': 'obsidian', 'fileName': 'snapshot.zip', 'fileSize': 100, 'requestKey': str(uuid4())}
    with e.client(workspace_id=ws, user_id=user, import_storage=storage) as client:
        accepted = client.post('/imports/packages', json=payload)
        assert accepted.status_code == 201
        before = admin(e, 'SELECT * FROM import_packages WHERE workspace_id=%s', (ws,))
        identical = client.post('/imports/packages', json=payload)
        assert identical.status_code == 201 and identical.json() == accepted.json()
        conflict = client.post('/imports/packages', json={**payload, **changed})
        assert conflict.status_code == 409 and conflict.json() == {'detail': 'request_key_conflict'}
        assert admin(e, 'SELECT * FROM import_packages WHERE workspace_id=%s', (ws,)) == before
        assert admin(e, 'SELECT count(*),sum(file_size) FROM import_packages WHERE workspace_id=%s', (ws,)) == [(1, 100)]
        assert client.get('/imports/packages/publications').json()['publications'] == []
        assert client.get('/items').json() == []
        assert admin(e, 'SELECT count(*) FROM import_objects WHERE workspace_id=%s', (ws,)) == [(0,)]
        # Configuration is server-owned: retry keeps the admission policy snapshot.
        with e.client(workspace_id=ws, user_id=user, import_storage=storage,
                      import_policy=replace(ImportPolicy(), compressed_bytes=1, workspace_concurrency=1)) as reconfigured:
            retry = reconfigured.post('/imports/packages', json=payload)
            assert retry.status_code == 201 and retry.json() == accepted.json()
        with e.client(import_storage=storage) as other:
            independent = other.post('/imports/packages', json=payload)
            assert independent.status_code == 201 and independent.json()['id'] != accepted.json()['id']
        admin(e, "UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (ws, user))
        assert client.post('/imports/packages', json=payload).status_code == 403


@pytest.mark.parametrize('conflicting', [False, True])
def test_concurrent_create_reuse_has_one_immutable_identity_and_reservation(env, conflicting):
    e, storage, jobs = env
    ws, user = uuid4(), 'identity-race|' + uuid4().hex
    payload = {'sourceKind': 'obsidian', 'fileName': 'snapshot.zip', 'fileSize': 100, 'requestKey': str(uuid4())}
    requests = [payload, {**payload, **({'fileName': 'other.zip', 'fileSize': 200} if conflicting else {})}]
    with e.client(workspace_id=ws, user_id=user, import_storage=storage) as client:
        # Initialize the synthetic tenant before exercising only create admission.
        assert client.get('/items').status_code == 200
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda body: client.post('/imports/packages', json=body), requests))
        assert sorted(r.status_code for r in responses) == ([201, 409] if conflicting else [201, 201])
        winner = next(r.json() for r in responses if r.status_code == 201)
        assert len(client.get('/imports/packages').json()) == 1
        if not conflicting:
            assert responses[0].json() == responses[1].json()
        for body in requests:
            retry = client.post('/imports/packages', json=body)
            identical = (body['sourceKind'], body['fileName'], body['fileSize']) == (winner['source_kind'], winner['file_name'], winner['file_size'])
            assert retry.status_code == (201 if identical else 409)
        assert admin(e, 'SELECT count(*),sum(file_size) FROM import_packages WHERE workspace_id=%s', (ws,)) == [(1, winner['file_size'])]
        assert admin(e, 'SELECT count(*) FROM import_objects WHERE workspace_id=%s', (ws,)) == [(0,)]
        assert client.get('/imports/packages/publications').json()['publications'] == []


def test_duplicate_history_keeps_canonical_receipt_and_one_publication(env):
    e, storage, jobs = env
    raw = archive_bytes([('a.md', 'canonical text'), ('image.png', b'skipped')])
    with e.client(import_storage=storage) as client:
        key = uuid4()
        canonical_id = session(client, raw, key=key)
        assert client.post(f'/imports/packages/{canonical_id}/finalize').status_code == 200
        assert ImportProcessor(jobs, storage).process_one() == 'completed'
        canonical = client.get(f'/imports/packages/{canonical_id}').json()
        payload = {'sourceKind': 'obsidian', 'fileName': 'snapshot.zip', 'fileSize': len(raw), 'requestKey': str(key)}
        before = admin(e, 'SELECT * FROM import_packages WHERE id=%s', (UUID(canonical_id),))
        assert client.post('/imports/packages', json=payload).json() == canonical
        conflict = client.post('/imports/packages', json={**payload, 'fileName': 'different.zip'})
        assert conflict.status_code == 409 and conflict.json() == {'detail': 'request_key_conflict'}
        assert admin(e, 'SELECT * FROM import_packages WHERE id=%s', (UUID(canonical_id),)) == before
        duplicate_id = session(client, raw)
        finalized = client.post(f'/imports/packages/{duplicate_id}/finalize')
        assert finalized.status_code == 200 and finalized.json() == canonical
        history = client.get('/imports/packages').json()
        assert history[0]['id'] == duplicate_id and history[0]['status'] == 'duplicate'
        assert history[0]['canonical_id'] == canonical_id
        assert client.get(f'/imports/packages/{history[0]["canonical_id"]}').json() == canonical
        assert canonical['status'] == 'completed_with_skips'
        assert (canonical['published_count'], canonical['skipped_count']) == (1, 1)
        assert len(client.get(f'/imports/packages/{canonical_id}/entries').json()['entries']) == 2
        assert len(client.get('/items').json()) == 1
        assert len(client.get('/imports/packages/publications').json()['publications']) == 1


@pytest.mark.parametrize('kind', ['notion', 'obsidian'])
def test_postgres_twelve_files_report_replay_and_cleanup(env, kind):
    """The production adapter through the real API/worker publication gate."""
    from pathlib import Path
    from app.import_staging.postgres import PostgresStagedObjects
    e, _, jobs = env
    values = {}
    for line in Path(__file__).parents[1].joinpath('.env.import-production.example').read_text().splitlines():
        if line.startswith('FLARE_IMPORT_') and '=' in line:
            name, value = line.split('=', 1)
            field = name.removeprefix('FLARE_IMPORT_').lower()
            if field in ImportPolicy.__dataclass_fields__:
                values[field] = int(value)
    policy = ImportPolicy(**values)
    policy.validate_postgres()
    storage = PostgresStagedObjects(e.runtime_url)
    worker_storage = PostgresStagedObjects(jobs.url)
    worker_storage.heartbeat('jobs')
    worker_storage.heartbeat('cleanup')
    contents = {
        f'folder/note-{i:02d}{(".md", ".markdown", ".txt", ".csv")[i % 4]}':
        (f'number,text\n{i},synthetic ZIP test\n' if i % 4 == 3 else f'# Note {i}\nExact text Привет 👋\n')
        for i in range(12)
    }
    raw = archive_bytes([*contents.items(), ('image.png', b'unsupported synthetic image')])
    with e.client(import_storage=storage, import_policy=policy) as client:
        assert client.get('/imports/packages/capabilities').json() == {
            'available': True, 'maxUploadBytes': policy.compressed_bytes,
        }
        id = enqueue(client, raw, kind)
        assert client.get('/items').json() == []
        processor = ImportProcessor(jobs, worker_storage)
        assert processor.process_one() == 'completed'
        report = client.get(f'/imports/packages/{id}').json()
        assert (report['status'], report['entry_count'], report['published_count'], report['skipped_count']) == (
            'completed_with_skips', 13, 12, 1,
        )
        entries = client.get(f'/imports/packages/{id}/entries').json()['entries']
        assert next(entry for entry in entries if entry['path'] == 'image.png')['skip_reason'] == 'unsupported_format'
        items = client.get('/items').json()
        assert len(items) == 12
        for item in items:
            detail = client.get(f'/items/{item["id"]}').json()
            assert detail['content'] == contents[item['relativePath']]
        assert enqueue(client, raw, kind) == id
        assert len(client.get('/items').json()) == 12
        assert len(client.get('/imports/packages/publications').json()['publications']) == 1
        for _ in range(3):
            processor.cleanup_one()
        assert admin(e, '''SELECT count(*) FROM import_staging_blocks b
            JOIN import_objects o ON o.key=b.key WHERE o.workspace_id=%s''',
            (next(iter(e.workspace_ids)),)) == [(0,)]
        assert admin(e, 'SELECT DISTINCT status FROM import_objects WHERE workspace_id=%s',
                     (next(iter(e.workspace_ids)),)) == [('deleted',)]
        assert admin(e, 'SELECT count(*) FROM analysis_jobs WHERE workspace_id=%s',
                     (next(iter(e.workspace_ids)),)) == [(0,)]
        assert admin(e, 'SELECT count(*) FROM analysis_daily_quotas WHERE workspace_id=%s',
                     (next(iter(e.workspace_ids)),)) == [(0,)]


def test_upload_context_io_runs_outside_event_loop_and_settles_cancellation():
    import asyncio
    import threading
    from contextlib import contextmanager
    from app.services.import_packages import ImportPackageService
    event_thread = threading.get_ident()
    entered, writing, release = threading.Event(), threading.Event(), threading.Event()
    events = []

    class Repository:
        identity = None
        def action(self, action, *args):
            events.append(action)
            if action == 'upload_claim':
                return {'key': 'test', 'token': 'test', 'fileSize': 4,
                        'policy': ImportPolicy().__dict__}
        def get(self, *args):
            return {}

    class Storage:
        @contextmanager
        def writer(self, key):
            assert threading.get_ident() != event_thread
            entered.set()
            try:
                yield self
            finally:
                assert not writing.is_set(), 'close raced an unfinished thread write'
                events.append('closed')
        def write(self, block):
            assert threading.get_ident() != event_thread
            writing.set()
            assert release.wait(2)
            writing.clear()

    async def stream():
        yield b'test'

    async def run():
        svc = ImportPackageService(Repository(), Storage(), ImportPolicy())
        task = asyncio.create_task(svc.upload(uuid4(), stream()))
        for _ in range(100):
            if writing.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set() and writing.is_set()
        task.cancel()
        await asyncio.sleep(0)
        assert 'closed' not in events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events[-2:] == ['closed', 'upload_abort']
        assert 'upload_done' not in events
    asyncio.run(run())
