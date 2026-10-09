"""Synthetic PostgreSQL staging checks against disposable restricted roles."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import importlib.util
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from app.import_staging.postgres import BLOCK_BYTES, PostgresStagedObjects, _Writer
from app.import_staging.policy import ImportPolicy
from app.models.database import Database, WorkspaceIdentity
from app.models.import_packages import ImportPackageError, ImportPackages, ImportWorkerJobs
from app.workers.import_worker import ImportProcessor
from test_zip_import import archive_bytes


class Fixture:
    def __init__(self):
        self.admin_url = os.environ['TEST_DATABASE_URL']
        self.app = PostgresStagedObjects(os.environ['DATABASE_URL'])
        self.worker = PostgresStagedObjects(os.environ['WORKER_DATABASE_URL'])
        self.jobs = ImportWorkerJobs(os.environ['WORKER_DATABASE_URL'])
        self.database = Database(os.environ['DATABASE_URL'])
        self.database.open()
        self.tenants = []

    def sql(self, query, parameters=()):
        with psycopg.connect(self.admin_url) as c:
            result = c.execute(query, parameters)
            return result.fetchall() if result.description else None

    def tenant(self):
        w, u = uuid4(), 'pg-staging|' + uuid4().hex
        self.sql('INSERT INTO workspaces(id,name) VALUES(%s,%s)', (w, 'Synthetic staging'))
        self.sql('INSERT INTO auth_users(id,email,password_hash,name,initial_workspace_id) VALUES(%s,%s,%s,%s,%s)',
                 (u, uuid4().hex + '@fixture.invalid', 'not-a-login', 'Fixture', w))
        self.sql("INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'owner')", (w, u))
        self.tenants.append((w, u))
        identity = WorkspaceIdentity(w, u)
        return identity, ImportPackages(self.database, identity)

    def claim(self, size, identity=None, policy=None):
        identity, repo = self.tenant() if identity is None else (identity, ImportPackages(self.database, identity))
        policy = policy or replace(ImportPolicy(), compressed_bytes=8*1024*1024)
        package = repo.action('create', payload={'requestKey': str(uuid4()), 'sourceKind': 'obsidian',
                             'fileName': 'synthetic.zip', 'fileSize': size, 'policy': asdict(policy)})['id']
        claim = repo.action('upload_claim', package)
        storage = self.app.for_upload(identity, claim['key'], claim['token'])
        return identity, repo, package, claim, storage

    def stage(self, raw, identity=None):
        identity, repo, package, claim, storage = self.claim(len(raw), identity)
        with storage.writer(claim['key']) as stream:
            for offset in range(0, len(raw), 17001):
                assert stream.write(raw[offset:offset+17001]) == len(raw[offset:offset+17001])
        repo.action('upload_done', package, {'token': str(claim['token']), 'bytes': len(raw),
                                          'hash': hashlib.sha256(raw).hexdigest()})
        return identity, repo, package, claim, storage

    def close(self):
        self.database.close()
        ids = [w for w, _ in self.tenants]
        users = [u for _, u in self.tenants]
        with psycopg.connect(self.admin_url) as c:
            c.execute('SET LOCAL session_replication_role=replica')
            c.execute('DELETE FROM import_staging_blocks WHERE key IN (SELECT key FROM import_objects WHERE workspace_id=ANY(%s))', (ids,))
            for table in ('import_publications', 'import_package_entries', 'import_objects', 'import_packages',
                          'chunks', 'document_versions', 'documents', 'workspace_members'):
                c.execute(f'DELETE FROM {table} WHERE workspace_id=ANY(%s)', (ids,))
            c.execute('DELETE FROM auth_users WHERE id=ANY(%s)', (users,))
            c.execute('DELETE FROM workspaces WHERE id=ANY(%s)', (ids,))
            c.execute('DELETE FROM import_staging_health')


@pytest.fixture
def db():
    if not all(os.getenv(k) for k in ('DATABASE_URL', 'TEST_DATABASE_URL', 'WORKER_DATABASE_URL')):
        pytest.skip('Disposable migrated PostgreSQL fixture required')
    fixture = Fixture()
    try:
        yield fixture
    finally:
        fixture.close()


@pytest.mark.integration
def test_restricted_roles_probe_heartbeat_ready_and_no_payload_sql(db):
    assert db.app.probe() and db.worker.probe()
    assert db.app.ready() is False
    db.worker.heartbeat('jobs')
    assert db.app.ready() is False
    db.worker.heartbeat('cleanup')
    assert db.app.ready() is True
    for mode, age in [('jobs', 241), ('cleanup', 31)]:
        db.sql("UPDATE import_staging_health SET touched_at=now()-make_interval(secs=>%s) WHERE mode=%s", (age, mode))
        assert db.app.ready() is False
        db.worker.heartbeat(mode)
    for storage, operation in [(db.app, lambda s: s.heartbeat('jobs')), (db.worker, lambda s: s.ready()),
                               (PostgresStagedObjects(db.admin_url), lambda s: s.probe())]:
        with pytest.raises(ImportPackageError, match='forbidden'):
            operation(storage)
    for url in (db.app.dsn, db.worker.dsn):
        for table in ('import_staging_blocks', 'import_staging_health'):
            for column in ('*', 'data' if table.endswith('blocks') else 'mode'):
                with psycopg.connect(url) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute(f'SELECT {column} FROM {table}')
        with psycopg.connect(url) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute('SELECT _import_staging_upload_guard(%s,%s)', ('a'*32+'-'+'b'*32, uuid4()))


@pytest.mark.integration
def test_stream_integrity_block_bounds_dedupe_cleanup_and_tombstone(db):
    started = time.monotonic()
    raw = archive_bytes([(f'notes/note-{n}.md', f'Exact Unicode Привет 👋 note {n}\n') for n in range(12)] + [('image.png', b'unsupported')])
    identity, repo, package, claim, _ = db.stage(raw)
    assert repo.action('finalize', package)['id'] == package
    job = db.jobs.claim(1)
    bound = db.worker.for_job(job)
    assert bound.size(claim['key']) == len(raw)
    with bound.reader(claim['key']) as stream:
        assert stream.read(0) == b''
        with pytest.raises(ValueError): stream.read()
        recovered = b''.join(iter(lambda: stream.read(31), b''))
    assert recovered == raw
    # Decoder receives only scratch; it never obtains PostgreSQL access.
    import tempfile
    processor = ImportProcessor(db.jobs, bound)
    with tempfile.TemporaryFile() as scratch:
        scratch.write(recovered)
        manifest = processor.decode(job, scratch, 'manifest')['manifest']
        db.jobs.step(job, 'manifest', manifest)
        for entry in manifest:
            parsed = processor.decode(job, scratch, 'file', entry['ordinal'])
            db.jobs.step(job, 'entry', parsed)
            if parsed['parsed']['status'] == 'prepared':
                db.jobs.step(job, 'publish', {'ordinal': entry['ordinal']})
    db.jobs.step(job, 'gate')
    assert db.sql('SELECT status,published_count,skipped_count FROM import_packages WHERE id=%s', (package,)) == [('completed_with_skips', 12, 1)]
    for table in ('analysis_jobs', 'analysis_daily_quotas', 'analysis_runs', 'flare_generation_runs'):
        assert db.sql(f'SELECT count(*) FROM {table} WHERE workspace_id=%s', (identity.workspace_id,)) == [(0,)]
    _, duplicate_repo, duplicate, _, _ = db.stage(raw, identity)
    assert duplicate_repo.action('finalize', duplicate)['id'] == package
    assert db.sql('SELECT count(*) FROM import_publications WHERE package_id=%s', (package,)) == [(1,)]
    # Durable cleanup retries remove active bytes, retaining object/admission metadata.
    obj = db.jobs.cleanup()
    retire = db.worker.for_cleanup(obj)
    retire.delete(obj['key']); retire.delete(obj['key'])
    assert db.sql('SELECT count(*) FROM import_staging_blocks WHERE key=%s', (obj['key'],)) == [(0,)]
    db.jobs.cleanup('done', obj['key'], obj['cleanup_token'])
    assert db.sql('SELECT status,storage_admitted_at IS NOT NULL,storage_bytes FROM import_objects WHERE key=%s', (obj['key'],)) == [('deleted', True, 0)]
    with pytest.raises(ImportPackageError, match='lease_lost'): retire.delete(obj['key'])
    print(f'PostgreSQL 12 supported + 1 skipped fixture: {time.monotonic()-started:.3f}s')


@pytest.mark.integration
def test_chunk_exact_retry_conflict_and_complete_seal(db):
    _, repo, package, claim, storage = db.claim(BLOCK_BYTES+7)
    storage._upload('begin'); storage._upload('begin')
    block = b'x' * BLOCK_BYTES
    storage._upload('append', 0, block)
    storage._upload('append', 0, block)
    assert db.sql('SELECT storage_bytes,storage_blocks FROM import_objects WHERE key=%s', (claim['key'],)) == [(BLOCK_BYTES, 1)]
    for ordinal, content in [(0, b'z'*BLOCK_BYTES), (2, b'y'*7), (1, b'y'*6), (1, b'y'*(BLOCK_BYTES+1))]:
        with pytest.raises(ImportPackageError): storage._upload('append', ordinal, content)
    with pytest.raises(ImportPackageError, match='integrity_failure'): storage._upload('finish')
    with psycopg.connect(db.app.dsn) as c:
        c.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)", (str(storage._identity.workspace_id), storage._identity.user_id))
        from psycopg.types.json import Jsonb
        with pytest.raises(psycopg.errors.RaiseException, match='integrity_failure'):
            c.execute("SELECT import_api('upload_done',%s,%s)", (package, Jsonb({'token': str(claim['token']), 'bytes': BLOCK_BYTES+7, 'hash': 'a'*64})))
    storage._upload('append', 1, b'y'*7); storage._upload('finish')
    repo.action('upload_done', package, {'token': str(claim['token']), 'bytes': BLOCK_BYTES+7, 'hash': 'a'*64})
    with pytest.raises(ImportPackageError, match='lease_lost'): storage._upload('append', 1, b'y'*7)


@pytest.mark.integration
@pytest.mark.parametrize('change', ['cancel', 'expire', 'revoke', 'disable'])
def test_upload_fenced_by_state_deadline_identity_and_cleanup(db, change):
    identity, repo, package, claim, storage = db.claim(3)
    storage._upload('begin')
    if change == 'cancel': repo.action('cancel', package)
    elif change == 'expire': db.sql("UPDATE import_packages SET upload_expires_at=now()-interval '1 second' WHERE id=%s", (package,))
    elif change == 'revoke': db.sql("UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s", (identity.workspace_id,))
    else: db.sql('UPDATE auth_users SET disabled=true WHERE id=%s', (identity.user_id,))
    with pytest.raises(ImportPackageError): storage._upload('append', 0, b'zip')
    assert db.sql('SELECT count(*) FROM import_staging_blocks WHERE key=%s', (claim['key'],)) == [(0,)]
    db.sql("UPDATE import_objects SET expires_at=now()-interval '1 second' WHERE key=%s", (claim['key'],))
    db.sql("UPDATE import_packages SET expires_at=now()-interval '1 second' WHERE id=%s", (package,))
    obj = db.jobs.cleanup()
    db.worker.for_cleanup(obj).delete(obj['key'])
    db.jobs.cleanup('done', obj['key'], obj['cleanup_token'])
    with pytest.raises(ImportPackageError): storage._upload('begin')


@pytest.mark.integration
@pytest.mark.parametrize('change', ['cancel', 'lease', 'generation', 'revoke', 'disable'])
def test_worker_reads_fail_closed_including_buffer_and_eof(db, change):
    identity, repo, package, claim, _ = db.stage(b'zip bytes')
    repo.action('finalize', package)
    job = db.jobs.claim(1); storage = db.worker.for_job(job)
    with storage.reader(claim['key']) as reader:
        assert reader.read(1) == b'z'
        if change == 'cancel': repo.action('cancel', package)
        elif change == 'lease': db.sql("UPDATE import_packages SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (package,))
        elif change == 'generation': db.sql('UPDATE import_packages SET generation=generation+1 WHERE id=%s', (package,))
        elif change == 'revoke': db.sql("UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s", (identity.workspace_id,))
        else: db.sql('UPDATE auth_users SET disabled=true WHERE id=%s', (identity.user_id,))
        with pytest.raises(ImportPackageError): reader.read(1)
    with pytest.raises(ImportPackageError): storage.size(claim['key'])


@pytest.mark.integration
def test_bindings_tenant_cross_key_and_cleanup_tokens(db):
    _, _, _, claim, storage = db.claim(3)
    other, _ = db.tenant()
    for selected in [db.app, db.app.for_upload(other, claim['key'], claim['token']),
                     db.app.for_upload(storage._identity, claim['key'], uuid4())]:
        with pytest.raises(ImportPackageError):
            with selected.writer(claim['key']): pass
    with pytest.raises(ImportPackageError):
        with storage.writer('a'*32+'-'+'b'*32): pass
    for action in [lambda: db.worker.size(claim['key']), lambda: db.worker.delete(claim['key']),
                   lambda: db.worker.for_cleanup({'key': claim['key'], 'cleanup_token': uuid4()}).delete(claim['key'])]:
        with pytest.raises(ImportPackageError): action()
    with pytest.raises(ValueError): db.app.for_upload(other, '../zip', uuid4())


@pytest.mark.integration
def test_global_live_reservation_and_rolling_hour_caps(db):
    # Synthetic content-free object reservations avoid generating 64MiB payload.
    claims = [db.claim(8*1024*1024) for _ in range(8)]
    for row in claims: row[-1]._upload('begin')
    ninth = db.claim(1)
    with pytest.raises(ImportPackageError, match='staged_quota'): ninth[-1]._upload('begin')
    db.sql("UPDATE import_objects SET status='deleted' WHERE key=ANY(%s)", ([row[3]['key'] for row in claims],))
    ninth[-1]._upload('begin')
    # Prior retired attempts still count toward churn, but admissions expire.
    db.sql("UPDATE import_objects SET bytes=16777216 WHERE key=ANY(%s)", ([row[3]['key'] for row in claims],))
    tenth = db.claim(1)
    with pytest.raises(ImportPackageError, match='staged_quota'): tenth[-1]._upload('begin')
    db.sql("UPDATE import_objects SET storage_admitted_at=now()-interval '61 minutes' WHERE status='deleted'")
    tenth[-1]._upload('begin')
    assert db.sql('SELECT count(*) FROM import_staging_blocks') == [(0,)]


@pytest.mark.integration
def test_concurrent_admission_and_retire_fences_paused_writer(db):
    rows = [db.claim(1) for _ in range(2)]
    retired = [db.claim(8*1024*1024) for _ in range(8)]
    db.sql("UPDATE import_objects SET status='deleted',storage_admitted_at=now(),bytes=16777216 WHERE key=ANY(%s)", ([r[3]['key'] for r in retired],))
    # Exactly one byte of global churn remains; concurrent begin is serialized.
    db.sql('UPDATE import_objects SET bytes=bytes-1 WHERE key=%s', (retired[0][3]['key'],))
    def begin(row):
        try: row[-1]._upload('begin'); return 'admitted'
        except ImportPackageError as error: return error.code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(begin, rows)) == ['admitted', 'staged_quota']
    admitted = next(row for row in rows if db.sql('SELECT storage_admitted_at IS NOT NULL FROM import_objects WHERE key=%s', (row[3]['key'],)) == [(True,)])
    _, repo, package, claim, storage = admitted
    # Pause before the first payload write, then retire the immutable key.
    repo.action('cancel', package)
    db.sql("UPDATE import_objects SET expires_at=now()-interval '1 second' WHERE key=%s", (claim['key'],))
    obj = db.jobs.cleanup()
    assert obj['key'] == claim['key']
    db.worker.for_cleanup(obj).delete(obj['key'])
    db.jobs.cleanup('done', obj['key'], obj['cleanup_token'])
    with pytest.raises(ImportPackageError, match='lease_lost'): storage._upload('append', 0, b'x')
    assert db.sql('SELECT count(*) FROM import_staging_blocks WHERE key=%s', (claim['key'],)) == [(0,)]


def test_writer_serial_close_late_write_and_block_memory_bound():
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Storage:
        def _upload(self, action, ordinal=None, data=None):
            if action == 'append':
                calls.append((ordinal, len(data)))
                entered.set(); assert release.wait(5)
    writer = _Writer(Storage(), BLOCK_BYTES+1)
    with ThreadPoolExecutor(2) as pool:
        writing = pool.submit(writer.write, b'x'*BLOCK_BYTES)
        assert entered.wait(5)
        closing = pool.submit(writer.close)
        assert not closing.done()
        release.set(); writing.result(); closing.result()
    assert calls == [(0, BLOCK_BYTES)] and not writer._buffer and writer.closed
    with pytest.raises(ValueError): writer.write(b'x')


def test_database_failure_message_is_fixed(monkeypatch):
    def unavailable(*args, **kwargs):
        assert kwargs['connect_timeout'] == 3
        assert 'statement_timeout=5000' in kwargs['options'] and 'lock_timeout=2000' in kwargs['options']
        raise psycopg.OperationalError('private DSN secret error')
    monkeypatch.setattr(psycopg, 'connect', unavailable)
    with pytest.raises(OSError, match='^storage_unavailable$'):
        PostgresStagedObjects('never exposed').ready()


@pytest.mark.integration
def test_eight_mib_hard_cap_and_bounded_large_stream(db):
    _, _, _, claim, storage = db.claim(8*1024*1024)
    started = time.monotonic()
    with storage.writer(claim['key']) as writer:
        for _ in range(32):
            writer.write(b'x'*BLOCK_BYTES)
            assert len(writer._buffer) < BLOCK_BYTES
        with pytest.raises(ImportPackageError, match='compressed_bytes'): writer.write(b'x')
    assert db.sql('SELECT storage_bytes,storage_blocks FROM import_objects WHERE key=%s', (claim['key'],)) == [(8*1024*1024, 32)]
    assert db.sql('SELECT max(octet_length(data)),sum(octet_length(data)) FROM import_staging_blocks WHERE key=%s', (claim['key'],)) == [(BLOCK_BYTES, 8*1024*1024)]
    _, _, _, oversized, blocked = db.claim(8*1024*1024+1, policy=replace(ImportPolicy(), compressed_bytes=16*1024*1024))
    with pytest.raises(ImportPackageError, match='compressed_bytes'):
        with blocked.writer(oversized['key']): pass
    assert db.sql('SELECT storage_admitted_at IS NULL FROM import_objects WHERE key=%s', (oversized['key'],)) == [(True,)]
    print(f'PostgreSQL 8MiB/32-block write fixture: {time.monotonic()-started:.3f}s')


@pytest.mark.integration
def test_cleanup_expired_token_retry_and_write_lock_timeout(db):
    _, repo, package, claim, storage = db.claim(3)
    storage._upload('begin')
    # A blocked object operation stops at the adapter's fixed two-second lock limit.
    with psycopg.connect(db.admin_url) as locked:
        locked.execute('SELECT key FROM import_objects WHERE key=%s FOR UPDATE', (claim['key'],))
        with pytest.raises(OSError, match='^storage_unavailable$'): storage._upload('append', 0, b'zip')
    assert db.sql('SELECT count(*) FROM import_staging_blocks WHERE key=%s', (claim['key'],)) == [(0,)]
    storage._upload('append', 0, b'zip')
    repo.action('cancel', package)
    db.sql("UPDATE import_objects SET expires_at=now()-interval '1 second' WHERE key=%s", (claim['key'],))
    obj = db.jobs.cleanup(); bound = db.worker.for_cleanup(obj)
    with pytest.raises(psycopg.errors.RaiseException, match='integrity_failure'):
        db.jobs.cleanup('done', claim['key'], obj['cleanup_token'])
    assert db.sql('SELECT status FROM import_objects WHERE key=%s', (claim['key'],)) == [('deleting',)]
    db.sql("UPDATE import_objects SET cleanup_expires_at=now()-interval '1 second' WHERE key=%s", (claim['key'],))
    with pytest.raises(ImportPackageError, match='lease_lost'): bound.delete(claim['key'])
    assert db.sql('SELECT count(*) FROM import_staging_blocks WHERE key=%s', (claim['key'],)) == [(1,)]
    replacement = db.jobs.cleanup()
    assert replacement['cleanup_token'] != obj['cleanup_token']
    with pytest.raises(ImportPackageError, match='lease_lost'): bound.delete(claim['key'])
    db.worker.for_cleanup(replacement).delete(claim['key'])
    # Lost ACK/restart: deletion is idempotent until the current cleanup lease is done.
    db.worker.for_cleanup(replacement).delete(claim['key'])
    db.jobs.cleanup('done', claim['key'], replacement['cleanup_token'])
    assert db.sql('SELECT status,storage_bytes,storage_blocks FROM import_objects WHERE key=%s', (claim['key'],)) == [('deleted', 0, 0)]


@pytest.mark.integration
def test_tiny_upload_churn_and_workspace_session_caps_retain_metadata(db):
    # Tiny retired attempts exhaust the independent admission-count cap before
    # consuming appreciable payload/WAL bytes. Tombstones are never purged.
    _, _, _, _, storage = db.claim(1)
    identity, repo = db.tenant()
    seed_package = storage._key.split('-')[0]
    for _ in range(128):
        key = uuid4().hex + '-' + uuid4().hex
        db.sql("INSERT INTO import_objects(key,workspace_id,package_id,status,bytes,expires_at,storage_admitted_at) VALUES(%s,%s,%s,'deleted',1,now(),now())",
               (key, storage._identity.workspace_id, seed_package))
    with pytest.raises(ImportPackageError, match='staged_quota'): storage._upload('begin')
    db.sql("UPDATE import_objects SET storage_admitted_at=now()-interval '61 minutes' WHERE status='deleted'")
    storage._upload('begin')
    assert db.sql("SELECT count(*) FROM import_objects WHERE status='deleted'") == [(128,)]
    for _ in range(120):
        package = repo.action('create', payload={'requestKey': str(uuid4()), 'sourceKind': 'obsidian',
                      'fileName': 'tiny.zip', 'fileSize': 1, 'policy': asdict(ImportPolicy())})['id']
        repo.action('cancel', package)
    with pytest.raises(psycopg.errors.RaiseException, match='concurrency_limit'):
        repo.action('create', payload={'requestKey': str(uuid4()), 'sourceKind': 'obsidian',
                    'fileName': 'tiny.zip', 'fileSize': 1, 'policy': asdict(ImportPolicy())})
    assert db.sql('SELECT count(*) FROM import_packages WHERE workspace_id=%s', (identity.workspace_id,)) == [(120,)]
    db.sql("UPDATE import_packages SET created_at=now()-interval '61 minutes' WHERE workspace_id=%s", (identity.workspace_id,))
    repo.action('create', payload={'requestKey': str(uuid4()), 'sourceKind': 'obsidian',
                'fileName': 'tiny.zip', 'fileSize': 1, 'policy': asdict(ImportPolicy())})
    assert db.sql('SELECT count(*) FROM import_packages WHERE workspace_id=%s', (identity.workspace_id,)) == [(121,)]


@pytest.mark.integration
def test_pg17_restricted_admin_ownership_grants_preserved_and_rollback(monkeypatch):
    """Clone the disposable baseline; exercise real NOSUPERUSER CREATEROLE DDL."""
    if not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('Disposable PostgreSQL bootstrap required')
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    bootstrap = make_conninfo(os.environ['TEST_DATABASE_URL'], dbname='template1')
    database, role = 'staging_' + uuid4().hex, 'staging_admin_' + uuid4().hex
    with psycopg.connect(bootstrap, autocommit=True) as c:
        if c.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone() != (True,):
            pytest.skip('Disposable bootstrap superuser required')
        assert int(c.execute('SHOW server_version_num').fetchone()[0])//10000 == 17
        source = psycopg.conninfo.conninfo_to_dict(os.environ['TEST_DATABASE_URL'])['dbname']
        c.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(database), sql.Identifier(source)))
        c.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB CREATEROLE INHERIT NOBYPASSRLS').format(sql.Identifier(role)))
    cloned_bootstrap = make_conninfo(bootstrap, dbname=database)
    admin = make_conninfo(cloned_bootstrap, user=role)
    spec = importlib.util.spec_from_file_location('staging_migration', Path(__file__).resolve().parents[1]/'migrations/versions/0022_postgres_import_staging.py')
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    class Op:
        def __init__(self, connection, fail=False): self.connection, self.fail = connection, fail
        def execute(self, statement):
            self.connection.execute(statement)
            if self.fail and statement.startswith('ALTER FUNCTION') and ' OWNER TO ' in statement:
                raise RuntimeError('Injected owner transfer failure')
    monkeypatch.setenv('FLARE_DATABASE_PROVIDER', 'self-managed')
    try:
        with psycopg.connect(cloned_bootstrap) as c:
            for signature in migration.FUNCTIONS:
                c.execute(sql.SQL('DROP FUNCTION public.{} CASCADE').format(sql.SQL(signature)))
            c.execute('DROP TABLE import_staging_blocks,import_staging_health')
            c.execute('DROP INDEX import_storage_admissions,import_package_creation_rate')
            c.execute('ALTER TABLE import_objects DROP COLUMN storage_admitted_at,DROP COLUMN storage_bytes,DROP COLUMN storage_blocks')
            c.execute("UPDATE alembic_version SET version_num='0021'")
            c.execute(sql.SQL('GRANT USAGE,CREATE ON SCHEMA public TO {} WITH GRANT OPTION').format(sql.Identifier(role)))
            for name, kind in c.execute("SELECT relname,relkind FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN('r','S') ORDER BY relkind='S'").fetchall():
                c.execute(sql.SQL('ALTER {} {} OWNER TO {}').format(sql.SQL('SEQUENCE' if kind=='S' else 'TABLE'), sql.Identifier('public', name), sql.Identifier(role)))
        def memberships(c):
            return c.execute("SELECT roleid,member,grantor,admin_option,inherit_option,set_option FROM pg_auth_members WHERE roleid='flare_job_executor'::regrole ORDER BY member,grantor").fetchall()
        for effective in (False, True):
            with psycopg.connect(cloned_bootstrap) as c:
                flag = sql.SQL('TRUE' if effective else 'FALSE')
                c.execute(sql.SQL('GRANT flare_job_executor TO {} WITH ADMIN TRUE,INHERIT {},SET {}').format(sql.Identifier(role), flag, flag))
            for fail in (False, True):
                with psycopg.connect(admin) as c:
                    before = memberships(c)
                    migration.op = Op(c, fail)
                    if fail:
                        with pytest.raises(RuntimeError, match='Injected'): migration.upgrade()
                        c.rollback()
                    else:
                        migration.upgrade()
                        assert memberships(c) == before
                        assert c.execute("SELECT pg_has_role(current_user,'flare_job_executor','SET'),pg_has_role(current_user,'flare_job_executor','USAGE')").fetchone() == (effective, effective)
                        assert c.execute("SELECT has_schema_privilege('flare_job_executor','public','CREATE')").fetchone() == (False,)
                        c.rollback()
                    assert memberships(c) == before
                    assert c.execute("SELECT to_regclass('public.import_staging_blocks')").fetchone() == (None,)
                    c.rollback()
        # Existing unsafe runtime edge is rejected without modifying membership.
        with psycopg.connect(cloned_bootstrap) as c:
            c.execute('GRANT flare_job_executor TO flare_app')
        with psycopg.connect(admin) as c:
            before = memberships(c); migration.op = Op(c)
            with pytest.raises(psycopg.errors.RaiseException, match='Unsafe'): migration.upgrade()
            c.rollback(); assert memberships(c) == before
        with psycopg.connect(cloned_bootstrap) as c:
            c.execute('REVOKE flare_job_executor FROM flare_app')
            c.execute(sql.SQL('GRANT flare_job_executor TO {} WITH ADMIN TRUE,INHERIT FALSE,SET FALSE').format(sql.Identifier(role)))
        # Commit an actual restricted-admin 0021→0022 migration.
        with psycopg.connect(admin) as c:
            before = memberships(c); migration.op = Op(c); migration.upgrade()
            assert memberships(c) == before
            assert c.execute("SELECT pg_has_role(current_user,'flare_job_executor','SET'),pg_has_role(current_user,'flare_job_executor','USAGE')").fetchone() == (False, False)
            c.execute("UPDATE alembic_version SET version_num='0022'")
    finally:
        with psycopg.connect(bootstrap, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
            c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
