"""Isolated runtime/readiness/supervisor checks; no cloud, provider or live DB."""
from dataclasses import asdict, fields
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import types

import pytest

from app.import_staging.policy import ImportPolicy
from app.workers import health_server, import_worker


@pytest.fixture
def production(monkeypatch, tmp_path):
    for field in fields(ImportPolicy):
        monkeypatch.setenv(f'FLARE_IMPORT_{field.name.upper()}', str(asdict(ImportPolicy())[field.name]))
    monkeypatch.setenv('FLARE_ENV', 'production')
    monkeypatch.setenv('FLARE_IMPORT_ENABLED', 'true')
    monkeypatch.setenv('FLARE_IMPORT_STORAGE_PROVIDER', 'postgres')
    monkeypatch.setenv('FLARE_IMPORT_WORKER_CONCURRENCY', '1')
    monkeypatch.setenv('WORKER_DATABASE_URL', 'postgresql://worker.test.invalid/runtime')
    monkeypatch.setenv('FLARE_WORKER_HEARTBEAT_DIR', str(tmp_path / 'private'))
    # The independently owned policy validation is exercised in its own tests.
    # Here the runtime must call it rather than substituting local defaults.
    calls = []
    monkeypatch.setattr(ImportPolicy, 'validate_postgres', lambda self: calls.append(self), raising=False)
    return calls


def test_production_requires_enabled_postgres_and_explicit_single_consumer(production, monkeypatch):
    settings = import_worker.load_import_runtime()
    assert settings.provider == 'postgres' and settings.poll_seconds == 1
    assert production == [settings.policy]
    for name, value in [
        ('FLARE_IMPORT_ENABLED', 'false'), ('FLARE_IMPORT_ENABLED', 'TRUE'),
        ('FLARE_IMPORT_STORAGE_PROVIDER', 'local'), ('FLARE_IMPORT_STORAGE_PROVIDER', 'other'),
        ('FLARE_IMPORT_WORKER_CONCURRENCY', '2'), ('WORKER_DATABASE_URL', ''),
        ('FLARE_WORKER_HEARTBEAT_DIR', ''),
    ]:
        with monkeypatch.context() as patch:
            patch.setenv(name, value)
            with pytest.raises(ValueError):
                import_worker.load_import_runtime()


@pytest.mark.parametrize('field', [field.name for field in fields(ImportPolicy)])
def test_production_requires_every_policy_field(production, monkeypatch, field):
    monkeypatch.delenv(f'FLARE_IMPORT_{field.upper()}')
    with pytest.raises(ValueError, match='Production import requires explicit'):
        import_worker.load_import_runtime()


def test_production_example_has_every_policy_field_within_declared_caps():
    example = Path(__file__).resolve().parents[1] / '.env.import-production.example'
    values = dict(line.split('=', 1) for line in example.read_text().splitlines() if line and not line.startswith('#'))
    keys = {f'FLARE_IMPORT_{field.name.upper()}' for field in fields(ImportPolicy)}
    assert keys <= values.keys()
    policy = ImportPolicy(**{field.name: int(values[f'FLARE_IMPORT_{field.name.upper()}']) for field in fields(ImportPolicy)})
    assert policy.compressed_bytes == 8 * 1024**2
    assert policy.expanded_bytes == 24 * 1024**2
    assert policy.entries == 500 and policy.file_bytes == 200_000
    assert policy.global_concurrency == policy.workspace_concurrency == 1
    assert policy.job_seconds == 180 and policy.cpu_seconds == 60
    assert policy.memory_bytes == 256 * 1024**2
    assert values['FLARE_IMPORT_WORKER_CONCURRENCY'] == '1'


def test_postgres_startup_probes_adapter_and_restricted_jobs_without_local_fallback(production, monkeypatch):
    settings = import_worker.load_import_runtime()
    events = []
    class Storage:
        def __init__(self, url): events.append(('storage', url))
        def probe(self): events.append('probe')
    module = types.ModuleType('app.import_staging.postgres')
    module.PostgresStagedObjects = Storage
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(import_worker, 'RuntimeImportWorkerJobs', lambda url: events.append(('jobs', url)))
    monkeypatch.setattr(import_worker, 'LocalStagedObjects', lambda *_: pytest.fail('local production fallback'))
    processor = import_worker.create_processor(settings, threading.Event())
    assert isinstance(processor.storage, Storage)
    assert events == [('storage', settings.database_url), 'probe', ('jobs', settings.database_url)]
    monkeypatch.setattr(Storage, 'probe', lambda self: (_ for _ in ()).throw(OSError('unavailable')))
    with pytest.raises(OSError):
        import_worker.create_processor(settings, threading.Event())


def test_runtime_database_connect_and_idle_queries_are_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr(import_worker.psycopg, 'connect', lambda *args, **kwargs: calls.append((args, kwargs)))
    jobs = object.__new__(import_worker.RuntimeImportWorkerJobs)
    jobs.url = 'postgresql://worker.test.invalid/runtime'
    jobs.connection()
    assert calls[0][1]['connect_timeout'] == 3
    assert calls[0][1]['options'] == '-c statement_timeout=30000 -c lock_timeout=3000'


def settings(directory):
    return import_worker.ImportRuntimeSettings('synthetic', 'postgres', None, str(directory), ImportPolicy())


@pytest.mark.parametrize('mode', ['jobs', 'cleanup'])
def test_consumers_run_separately_and_stamp_only_after_successful_database_heartbeat(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(import_worker.time, 'monotonic', lambda: 1000)
    calls = []
    processor = types.SimpleNamespace(
        storage=types.SimpleNamespace(heartbeat=lambda value: calls.append(('heartbeat', value))),
        process_one=lambda: calls.append('job'), cleanup_one=lambda: calls.append('cleanup'),
    )
    assert import_worker.run_loop(processor, settings(tmp_path), threading.Event(), mode=mode, once=True) == 0
    assert calls == [('heartbeat', mode), 'job' if mode == 'jobs' else 'cleanup', ('heartbeat', mode)]
    path = tmp_path / f'{mode}.json'
    assert json.loads(path.read_text()) == {'checked_at': 1000}
    assert path.stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    assert not (tmp_path / f'{"cleanup" if mode == "jobs" else "jobs"}.json').exists()


def test_failed_database_roundtrip_never_refreshes_local_readiness_or_logs_exception(tmp_path, monkeypatch, caplog):
    now = [1000]
    monkeypatch.setattr(import_worker.time, 'monotonic', lambda: now[0])
    calls = []
    def heartbeat(mode):
        calls.append(mode)
        if len(calls) > 1:
            raise OSError('synthetic-private-dsn-or-row')
    def process(): now[0] = 1300
    processor = types.SimpleNamespace(storage=types.SimpleNamespace(heartbeat=heartbeat), process_one=process)
    assert import_worker.run_loop(processor, settings(tmp_path), threading.Event(), mode='jobs', once=True) == 1
    assert json.loads((tmp_path / 'jobs.json').read_text()) == {'checked_at': 1000}
    assert 'database_or_storage_unavailable' in caplog.text
    assert 'synthetic-private-dsn-or-row' not in caplog.text


def test_operation_failure_does_not_renew_heartbeat(tmp_path, monkeypatch):
    calls = []
    def fail(): raise import_worker.psycopg.OperationalError('synthetic outage')
    processor = types.SimpleNamespace(storage=types.SimpleNamespace(heartbeat=lambda mode: calls.append(mode)), process_one=fail)
    assert import_worker.run_loop(processor, settings(tmp_path), threading.Event(), mode='jobs', once=True) == 1
    assert calls == ['jobs']


def test_stop_interrupts_wait_without_starting_another_job(tmp_path):
    stop = threading.Event()
    calls = []
    def process():
        calls.append('one')
        stop.set()
    processor = types.SimpleNamespace(storage=types.SimpleNamespace(heartbeat=lambda mode: None), process_one=process)
    assert import_worker.run_loop(processor, settings(tmp_path), stop, mode='jobs') == 0
    assert calls == ['one']


def test_import_cli_failure_is_sanitized_and_restores_signal_handlers(production, monkeypatch, caplog):
    monkeypatch.setenv('FLARE_IMPORT_STORAGE_PROVIDER', 'synthetic-private-provider')
    monkeypatch.setattr(sys, 'argv', ['import_worker', '--once'])
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    assert import_worker.main() == 1
    assert 'startup_or_runtime_failure' in caplog.text
    assert 'synthetic-private-provider' not in caplog.text
    assert {sig: signal.getsignal(sig) for sig in handlers} == handlers


def test_import_cli_removes_its_readiness_stamp_on_exit(production, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['import_worker', '--mode', 'cleanup', '--once'])
    monkeypatch.setattr(import_worker, 'create_processor', lambda settings, stop: types.SimpleNamespace(
        storage=types.SimpleNamespace(heartbeat=lambda mode: None), cleanup_one=lambda: None))
    assert import_worker.main() == 0
    assert not (Path(os.environ['FLARE_WORKER_HEARTBEAT_DIR']) / 'cleanup.json').exists()


def test_processor_uses_immutable_job_and_cleanup_bindings(monkeypatch):
    raw = b'synthetic bounded object'
    job = {'id': 'synthetic-package', 'object_key': 'server-key', 'policy': asdict(ImportPolicy()),
           'file_size': len(raw), 'archive_hash': hashlib.sha256(raw).hexdigest()}
    obj = {'key': 'server-key', 'cleanup_token': 'synthetic-cleanup-lease'}
    calls = []
    class Jobs:
        def claim(self, limit): return job
        def step(self, value, action, data=None): calls.append(('step', action)); return {}
        def cleanup(self, action='claim', key=None, token=None):
            calls.append(('cleanup', action))
            return obj if action == 'claim' else None
    class Storage:
        def for_job(self, value):
            assert value is job
            calls.append('bind-job')
            return types.SimpleNamespace(reader=lambda key: io.BytesIO(raw))
        def for_cleanup(self, value):
            assert value is obj
            calls.append('bind-cleanup')
            return types.SimpleNamespace(delete=lambda key: calls.append(('delete', key)))
        def reader(self, key): pytest.fail('unbound read')
        def delete(self, key): pytest.fail('unbound delete')
    processor = import_worker.ImportProcessor(Jobs(), Storage())
    monkeypatch.setattr(processor, 'decode', lambda *args: {'manifest': []})
    assert processor.process_one() == 'completed'
    assert processor.cleanup_one() == 'deleted'
    assert 'bind-job' in calls and 'bind-cleanup' in calls
    assert calls.index(('cleanup', 'check')) < calls.index('bind-cleanup') < calls.index(('delete', 'server-key'))


def stamp(monkeypatch, directory, jobs=1000, cleanup=1000):
    monkeypatch.setenv('FLARE_IMPORT_ENABLED', 'true')
    monkeypatch.setenv('FLARE_WORKER_HEARTBEAT_DIR', str(directory))
    for mode, checked in [('jobs', jobs), ('cleanup', cleanup)]:
        monkeypatch.setattr(import_worker.time, 'monotonic', lambda checked=checked: checked)
        import_worker.record_heartbeat(str(directory), mode)


def test_readiness_keeps_disabled_import_compatible_but_requires_both_enabled_consumers(monkeypatch, tmp_path):
    monkeypatch.setenv('FLARE_IMPORT_ENABLED', 'false')
    monkeypatch.delenv('FLARE_WORKER_HEARTBEAT_DIR', raising=False)
    assert health_server.import_consumers_ready(now=1000)
    monkeypatch.setenv('FLARE_IMPORT_ENABLED', 'true')
    assert not health_server.import_consumers_ready(now=1000)
    stamp(monkeypatch, tmp_path)
    assert health_server.import_consumers_ready(now=1000)
    (tmp_path / 'cleanup.json').unlink()
    assert not health_server.import_consumers_ready(now=1000)


@pytest.mark.parametrize('jobs,cleanup,expected', [(760, 970, True), (759, 1000, False), (1000, 969, False), (1001, 1000, False)])
def test_readiness_expires_blocked_job_or_cleanup_loops(monkeypatch, tmp_path, jobs, cleanup, expected):
    stamp(monkeypatch, tmp_path, jobs, cleanup)
    assert health_server.import_consumers_ready(now=1000) is expected


@pytest.mark.parametrize('content', ['not-json', '{"checked_at":true}', '{"checked_at":NaN}', '{"checked_at":"1000"}', 'x' * 129])
def test_malformed_or_unbounded_heartbeat_is_unready(monkeypatch, tmp_path, content):
    stamp(monkeypatch, tmp_path)
    (tmp_path / 'jobs.json').write_text(content)
    assert not health_server.import_consumers_ready(now=1000)


def test_readiness_rejects_public_or_symlinked_heartbeat_files(monkeypatch, tmp_path):
    stamp(monkeypatch, tmp_path)
    path = tmp_path / 'jobs.json'
    path.chmod(0o644)
    assert not health_server.import_consumers_ready(now=1000)
    path.unlink()
    path.symlink_to(tmp_path / 'cleanup.json')
    assert not health_server.import_consumers_ready(now=1000)


@pytest.mark.parametrize('path', ['/', '/health', '/ready'])
def test_worker_health_aliases_report_unavailable_when_consumers_are_not_ready(monkeypatch, path):
    monkeypatch.setattr(health_server, 'import_consumers_ready', lambda: False)
    handler = object.__new__(health_server.HealthHandler)
    codes, headers = [], {}
    handler.path, handler.wfile = path, io.BytesIO()
    handler.send_response = codes.append
    handler.send_header = lambda key, value: headers.update({key: value})
    handler.end_headers = lambda: None
    handler.do_GET()
    assert codes == [503]
    assert json.loads(handler.wfile.getvalue()) == {'status': 'unavailable', 'role': 'worker'}
    assert headers['Cache-Control'] == 'no-store'


def test_health_server_startup_failure_never_interpolates_environment(monkeypatch, caplog):
    monkeypatch.setenv('PORT', 'synthetic-private-value')
    assert health_server.main() == 1
    assert 'startup_or_runtime_failure' in caplog.text
    assert 'synthetic-private-value' not in caplog.text


@pytest.mark.parametrize('exit_child,exit_status,enabled', [
    ('app.workers.health_server', 7, True), ('app.workers.analysis_worker', 0, True),
    ('app.workers.import_worker:jobs', 6, True), ('app.workers.import_worker:cleanup', 8, True),
    ('app.workers.analysis_worker', 0, False),
    ('signal-supervisor', 0, True),
])
def test_supervisor_stops_all_children_if_any_consumer_exits(tmp_path, exit_child, exit_status, enabled):
    log = tmp_path / 'events.jsonl'
    fake_python = tmp_path / 'fake-python'
    fake_python.write_text(f'''#!{sys.executable}
import json, os, signal, sys, time
label = sys.argv[2]
if '--mode' in sys.argv: label += ':' + sys.argv[sys.argv.index('--mode') + 1]
def record(event):
    with open(os.environ['TEST_EVENTS'], 'a') as stream:
        stream.write(json.dumps({{'event':event,'label':label,'pid':os.getpid()}}) + '\\n')
def stop(*args):
    record('stopped')
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
record('started')
for _ in range(300):
    try:
        with open(os.environ['TEST_EVENTS']) as stream:
            count = sum(json.loads(line)['event'] == 'started' for line in stream)
    except FileNotFoundError: count = 0
    if count >= int(os.environ['TEST_EXPECTED_CHILDREN']): break
    time.sleep(0.01)
if label == os.environ['TEST_EXIT_CHILD']:
    sys.exit(int(os.environ['TEST_EXIT_STATUS']))
while True: time.sleep(0.02)
''')
    fake_python.chmod(0o700)
    commands = tmp_path / 'commands'
    commands.mkdir()
    tar = commands / 'tar'
    tar.write_text('''#!/bin/sh
for value in "$@"; do target=$value; done
mkdir -p "$target/antenv/bin"
cp "$TEST_FAKE_PYTHON" "$target/antenv/bin/python"
''')
    tar.chmod(0o700)
    environment = {**os.environ, 'PATH': f'{commands}:{os.defpath}', 'FLARE_IMPORT_ENABLED': str(enabled).lower(),
                   'TEST_FAKE_PYTHON': str(fake_python), 'TEST_EVENTS': str(log), 'TEST_EXIT_CHILD': exit_child,
                   'TEST_EXIT_STATUS': str(exit_status), 'TEST_EXPECTED_CHILDREN': '4' if enabled else '2'}
    script = Path(__file__).resolve().parents[1] / 'deploy/bootstrap_flare_worker.sh'
    process = subprocess.Popen(['bash', str(script)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        if exit_child == 'signal-supervisor':
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.exists() and len(log.read_text().splitlines()) == 4:
                    break
                time.sleep(0.01)
            process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=15)
        expected_status = 0 if exit_child == 'signal-supervisor' else (exit_status or 1)
        assert process.returncode == expected_status, (stdout, stderr)
        events = [json.loads(line) for line in log.read_text().splitlines()]
        started = {event['label'] for event in events if event['event'] == 'started'}
        expected = {'app.workers.health_server', 'app.workers.analysis_worker'}
        if enabled: expected |= {'app.workers.import_worker:jobs', 'app.workers.import_worker:cleanup'}
        assert started == expected
        assert {event['label'] for event in events if event['event'] == 'stopped'} == expected - {exit_child}
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
